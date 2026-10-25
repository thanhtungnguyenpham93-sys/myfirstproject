#!/usr/bin/env python3
"""Pencil Video Studio — ảnh → video vẽ chì, với Tkinter hoặc dòng lệnh.

Python >= 3.10; pip install numpy Pillow; cài FFmpeg có encoder libx264.
Không cần OpenCV, Internet hay dịch vụ AI. Xem README.md để sử dụng.
"""
from __future__ import annotations

import argparse
import contextlib
from dataclasses import asdict, dataclass, fields, replace
import json
import logging
import math
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable
import warnings

try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps, UnidentifiedImageError
except ImportError as exc:
    raise SystemExit("Thiếu thư viện. Chạy: python -m pip install numpy Pillow") from exc

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:
    tk = None

APP_NAME = "Pencil Video Studio"
VERSION = "2.0.0"
LOG = logging.getLogger(__name__)
MAX_FILES = 200
Image.MAX_IMAGE_PIXELS = 40_000_000
PRESETS = {
    "HD ngang · 1280 × 720": (1280, 720),
    "HD dọc · 720 × 1280": (720, 1280),
    "Vuông · 1080 × 1080": (1080, 1080),
    "Full HD ngang · 1920 × 1080": (1920, 1080),
    "Full HD dọc · 1080 × 1920": (1080, 1920),
}
FITS = {"Vừa khung (giữ toàn ảnh)": "contain", "Lấp đầy (cắt viền)": "cover"}
ORDERS = {"Nét ngang zíc zắc": "horizontal", "Nét dọc zíc zắc": "vertical", "Từng ô ngẫu nhiên": "tiles"}
EFFECTS = {"Chì đen trắng": "pencil", "Chì màu": "color"}
Report = Callable[..., None]


class Cancelled(Exception):
    def __init__(self, outputs=()):
        super().__init__("Đã dừng xuất video.")
        self.outputs = list(outputs)


class BatchError(RuntimeError):
    def __init__(self, message, outputs=()):
        super().__init__(message)
        self.outputs = list(outputs)


def check_cancel(cancel: threading.Event):
    if cancel.is_set():
        raise Cancelled()


@dataclass(frozen=True)
class RenderConfig:
    width: int = 1280
    height: int = 720
    fps: int = 24
    duration: float = 8.0
    hold: float = 2.0
    fit: str = "contain"
    order: str = "horizontal"
    effect: str = "pencil"
    contrast: float = 1.2
    softness: float = 8.0
    texture: float = 0.08
    safe_margin: bool = False
    show_pencil: bool = True
    merge: bool = False

    def validate(self):
        for name in ("width", "height", "fps"):
            value = getattr(self, name)
            if type(value) is not int:
                raise ValueError(f"{name} phải là số nguyên.")
        if not all(16 <= v <= 1920 and v % 2 == 0 for v in (self.width, self.height)):
            raise ValueError("Chiều rộng/cao phải là số chẵn từ 16 đến 1920.")
        if not 1 <= self.fps <= 60:
            raise ValueError("FPS phải nằm trong khoảng 1–60.")
        limits = {"duration": (0.1, 600), "hold": (0, 120), "contrast": (0.2, 3),
                  "softness": (1, 30), "texture": (0, 0.3)}
        for name, (low, high) in limits.items():
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
                raise ValueError(f"{name} phải là số hữu hạn.")
            if not low <= value <= high:
                raise ValueError(f"{name} phải nằm trong khoảng {low}–{high}.")
        for name, choices in (("fit", FITS.values()), ("order", ORDERS.values()), ("effect", EFFECTS.values())):
            if getattr(self, name) not in choices:
                raise ValueError(f"Giá trị {name} không hợp lệ.")
        for name in ("safe_margin", "show_pencil", "merge"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} phải là true hoặc false.")
        return self

    @property
    def draw_frames(self):
        return max(2, round(self.duration * self.fps))

    @property
    def frame_count(self):
        return self.draw_frames + round(self.hold * self.fps)


def settings_path():
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming")))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "pencil-video-studio" / "settings.json"


def save_settings(path: Path, cfg: RenderConfig, files: list[str], output: str):
    """Ghi tệp tạm cùng thư mục rồi thay thế nguyên tử; không nuốt lỗi I/O."""
    cfg.validate()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"version": 2, "render": asdict(cfg), "files": files, "output": output}
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".settings-", suffix=".json", delete=False) as fh:
            tmp = Path(fh.name)
            json.dump(data, fh, ensure_ascii=False, indent=2, allow_nan=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def load_settings(path: Path):
    defaults = (RenderConfig(), [], str(Path.home() / "Videos" / "PencilVideoStudio"))
    if not Path(path).exists():
        return defaults
    try:
        if Path(path).stat().st_size > 1_000_000:
            raise ValueError("Tệp cấu hình quá lớn.")
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 2:
            raise ValueError("Phiên bản cấu hình không được hỗ trợ.")
        values = data.get("render", {})
        if not isinstance(values, dict):
            raise ValueError("Cấu hình render phải là một đối tượng.")
        known = {f.name for f in fields(RenderConfig)}
        cfg = RenderConfig(**{k: v for k, v in values.items() if k in known}).validate()
        files = data.get("files", [])
        if not isinstance(files, list) or len(files) > MAX_FILES or not all(isinstance(f, str) for f in files):
            raise ValueError("Danh sách ảnh không hợp lệ.")
        output = data.get("output", defaults[2])
        if not isinstance(output, str) or not output.strip():
            raise ValueError("Thư mục xuất không hợp lệ.")
        return cfg, [f for f in files if Path(f).is_file()], output
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"Không đọc được cấu hình {path}: {exc}") from exc


def find_ffmpeg():
    executable = shutil.which("ffmpeg")
    if not executable:
        raise RuntimeError("Không tìm thấy FFmpeg. Hãy cài FFmpeg và thêm vào PATH rồi mở lại ứng dụng.")
    try:
        result = subprocess.run([executable, "-hide_banner", "-encoders"], capture_output=True,
                                text=True, errors="replace", timeout=15, **subprocess_options())
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Không chạy được FFmpeg: {exc}") from exc
    if result.returncode or not any("libx264" in line.split() for line in result.stdout.splitlines()):
        raise RuntimeError("Cần bản FFmpeg có encoder libx264 để xuất MP4/H.264.")
    return executable


def subprocess_options():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}


def load_image(path: Path, cfg: RenderConfig):
    """Sửa hướng EXIF, ghép nền trắng cho ảnh trong suốt, giới hạn kích thước."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as source:
                if getattr(source, "is_animated", False):
                    source.seek(0)
                source = ImageOps.exif_transpose(source)
                rgba = source.convert("RGBA")
                white = Image.new("RGBA", rgba.size, "white")
                white.alpha_composite(rgba)
                rgb = white.convert("RGB")
        margin = 0.05 if cfg.safe_margin else 0
        box = (max(1, round(cfg.width * (1 - 2 * margin))), max(1, round(cfg.height * (1 - 2 * margin))))
        fit = ImageOps.contain if cfg.fit == "contain" else ImageOps.fit
        scaled = fit(rgb, box, method=Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (cfg.width, cfg.height), "white")
        canvas.paste(scaled, ((cfg.width - scaled.width) // 2, (cfg.height - scaled.height) // 2))
        return canvas
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise ValueError(f"Không đọc được ảnh '{path.name}': {exc}") from exc


class PencilRenderer:
    """Chuẩn bị mỗi ảnh một lần, phát từng khung hình thay vì lưu cả video vào RAM."""
    def __init__(self, path: Path, cfg: RenderConfig, cancel: threading.Event):
        self.cfg = cfg.validate()
        check_cancel(cancel)
        rgb = load_image(Path(path), cfg)
        gray = ImageEnhance.Contrast(ImageOps.grayscale(rgb)).enhance(cfg.contrast)
        blurred = ImageOps.invert(gray).filter(ImageFilter.GaussianBlur(cfg.softness))
        g = np.asarray(gray, dtype=np.float32)
        dodge = np.clip(g * 255.0 / np.maximum(255.0 - np.asarray(blurred, dtype=np.float32), 1.0), 0, 255)
        edge = np.asarray(gray.filter(ImageFilter.FIND_EDGES), dtype=np.float32).copy()
        # FIND_EDGES giữ pixel biên: bỏ khung đen giả ở cạnh ảnh.
        edge[[0, -1], :] = 0
        edge[:, [0, -1]] = 0
        line = np.clip(255.0 - edge * 1.8, 0, 255)
        tone = np.minimum(dodge, 0.74 * g + 66)
        pencil = np.minimum(tone, line)
        rng = np.random.default_rng(2026)
        grain = rng.normal(0, cfg.texture * 18, g.shape).astype(np.float32)
        self.paper = np.clip(252.0 + grain, 0, 255).astype(np.float32)
        self.lines = np.minimum(line + grain, self.paper).astype(np.float32)
        if cfg.effect == "color":
            color = np.asarray(rgb, dtype=np.float32)
            target = 0.6 * color + 0.4 * pencil[:, :, None]
        else:
            target = np.repeat(pencil[:, :, None], 3, axis=2)
        self.target = np.clip(target + grain[:, :, None], 0, 255).astype(np.uint8)
        self.rank = self._rank_map()
        self._final = Image.fromarray(self.target)
        check_cancel(cancel)

    def _rank_map(self):
        h, w = self.cfg.height, self.cfg.width
        y, x = np.indices((h, w), dtype=np.float32)
        band = max(4, round(min(w, h) / 70))
        if self.cfg.order == "horizontal":
            rows = np.floor(y / band)
            along = np.where(rows % 2 == 0, x / w, 1 - x / w)
            rank = (rows + along) / math.ceil(h / band)
        elif self.cfg.order == "vertical":
            cols = np.floor(x / band)
            along = np.where(cols % 2 == 0, y / h, 1 - y / h)
            rank = (cols + along) / math.ceil(w / band)
        else:
            tile = max(16, round(min(w, h) / 10))
            nx, ny = math.ceil(w / tile), math.ceil(h / tile)
            order = np.random.default_rng(42).permutation(nx * ny)
            ids = (y.astype(np.int32) // tile) * nx + x.astype(np.int32) // tile
            rank = (order[ids] + (y % tile + x % tile / tile) / tile) / (nx * ny)
        return np.asarray(rank, dtype=np.float32)

    def frame(self, progress: float):
        progress = min(1.0, max(0.0, progress))
        if progress >= 1:
            return self._final.copy()
        # Hai lượt: phác nét trước, tô sắc độ sau.
        line_progress = min(1.0, progress / 0.6)
        shade_progress = max(0.0, (progress - 0.6) / 0.4)
        line_mask = np.clip((line_progress - self.rank) * 220, 0, 1)
        mono = self.paper + (self.lines - self.paper) * line_mask
        shade_mask = np.clip((shade_progress - self.rank) * 220, 0, 1)[:, :, None]
        pixels = mono[:, :, None] + (self.target.astype(np.float32) - mono[:, :, None]) * shade_mask
        frame = Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8))
        if self.cfg.show_pencil and progress > 0:
            phase = line_progress if progress < 0.6 else shade_progress
            # Lấy vị trí gần nét đang vẽ trên lưới giảm mẫu để tránh tìm kiếm toàn ảnh.
            step = max(1, min(self.cfg.width, self.cfg.height) // 180)
            small = self.rank[::step, ::step]
            index = int(np.argmin(np.abs(small - phase)))
            row, col = np.unravel_index(index, small.shape)
            self._pencil(frame, col * step, row * step)
        return frame

    @staticmethod
    def _pencil(image, x, y):
        size = max(12, round(min(image.size) * 0.09))
        d = ImageDraw.Draw(image)
        d.polygon([(x, y), (x + size * 0.24, y - size * 0.43),
                   (x + size * 0.48, y - size * 0.21)], fill="#e9c498")
        d.polygon([(x + size * 0.24, y - size * 0.43), (x + size, y - size * 1.2),
                   (x + size * 1.24, y - size * 0.98), (x + size * 0.48, y - size * 0.21)],
                  fill="#dca832", outline="#5b472a")
        d.line([(x, y), (x + size * 0.13, y - size * 0.15)], fill="#252525", width=max(2, size // 18))


class VideoWriter:
    """Encoder riêng, stderr vào tệp; luồng giám sát giải phóng pipe khi hủy."""
    def __init__(self, output: Path, cfg: RenderConfig, ffmpeg: str, cancel: threading.Event):
        self.output, self.cfg, self.cancel = output, cfg, cancel
        self._done = threading.Event()
        self._process = None
        self._watcher = None
        self._log = None
        self._temp = None
        self._reserved = False
        try:
            # Giữ tên đầu ra độc quyền, không ghi đè video sẵn có.
            with output.open("xb"):
                self._reserved = True
            handle, filename = tempfile.mkstemp(prefix=".render-", suffix=".mp4", dir=output.parent)
            os.close(handle)
            self._temp = Path(filename)
            self._log = tempfile.TemporaryFile()
            command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                       "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{cfg.width}x{cfg.height}",
                       "-r", str(cfg.fps), "-i", "pipe:0", "-an", "-c:v", "libx264",
                       "-preset", "veryfast", "-crf", "18", "-threads", "2",
                       "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(self._temp)]
            self._process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                             stderr=self._log, **subprocess_options())
            self._watcher = threading.Thread(target=self._watch_cancel, daemon=True)
            self._watcher.start()
        except BaseException:
            self.close()
            raise

    def _watch_cancel(self):
        while not self._done.wait(0.1):
            if self.cancel.is_set():
                with contextlib.suppress(OSError):
                    self._process.kill()
                return

    def diagnostic(self):
        self._log.seek(0, os.SEEK_END)
        self._log.seek(max(0, self._log.tell() - 6000))
        return self._log.read().decode("utf-8", errors="replace").strip()

    def write(self, frame: Image.Image):
        check_cancel(self.cancel)
        if frame.mode != "RGB" or frame.size != (self.cfg.width, self.cfg.height):
            raise ValueError("Khung hình không khớp định dạng RGB/kích thước video.")
        try:
            self._process.stdin.write(frame.tobytes())
        except (BrokenPipeError, OSError) as exc:
            check_cancel(self.cancel)
            raise RuntimeError(f"FFmpeg ngừng nhận khung hình: {self.diagnostic() or str(exc)}") from exc

    def finish(self):
        check_cancel(self.cancel)
        try:
            self._process.stdin.close()
            code = self._process.wait(timeout=120)
        except (OSError, subprocess.TimeoutExpired) as exc:
            check_cancel(self.cancel)
            raise RuntimeError(f"FFmpeg không hoàn tất: {self.diagnostic() or str(exc)}") from exc
        check_cancel(self.cancel)
        if code != 0 or self._temp.stat().st_size == 0:
            raise RuntimeError(f"Xuất MP4 thất bại: {self.diagnostic() or f'FFmpeg exit {code}'}")
        os.replace(self._temp, self.output)
        self._reserved = False

    def close(self):
        self._done.set()
        if self._process is not None:
            if self._process.poll() is None:
                with contextlib.suppress(OSError):
                    self._process.kill()
            with contextlib.suppress(OSError):
                self._process.wait(timeout=10)
            if self._process.stdin is not None:
                with contextlib.suppress(OSError):
                    self._process.stdin.close()
        if self._watcher is not None:
            self._watcher.join(timeout=2)
        if self._log is not None:
            self._log.close()
        if self._temp is not None:
            self._temp.unlink(missing_ok=True)
        if self._reserved:
            self.output.unlink(missing_ok=True)
            self._reserved = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def run_batch(files, cfg: RenderConfig, output, cancel: threading.Event, report: Report = lambda **kw: None):
    cfg.validate()
    paths = [Path(f).expanduser().resolve() for f in files]
    if not 1 <= len(paths) <= MAX_FILES:
        raise ValueError(f"Hãy chọn từ 1 đến {MAX_FILES} ảnh.")
    for path in paths:
        if not path.is_file():
            raise ValueError(f"Không tìm thấy ảnh: {path}")
    check_cancel(cancel)
    ffmpeg = find_ffmpeg()
    out = Path(output).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    job = Path(tempfile.mkdtemp(prefix=time.strftime("pencil_%Y%m%d_%H%M%S_"), dir=out))
    outputs = []
    started, done, last_report = time.monotonic(), 0, 0.0
    total = len(paths) * cfg.frame_count

    def render(path, writer, index):
        nonlocal done, last_report
        report(status=f"Chuẩn bị ảnh {index + 1}/{len(paths)}: {path.name}")
        renderer = PencilRenderer(path, cfg, cancel)
        for frame_index in range(cfg.frame_count):
            check_cancel(cancel)
            progress = min(1, frame_index / (cfg.draw_frames - 1))
            frame = renderer.frame(progress)
            writer.write(frame)
            done += 1
            now = time.monotonic()
            if now - last_report >= 0.25 or done == total:
                elapsed = now - started
                eta = elapsed * (total - done) / done
                preview = frame.copy()
                preview.thumbnail((640, 480), Image.Resampling.LANCZOS)
                report(progress=done / total, status=f"Ảnh {index + 1}/{len(paths)} · {done}/{total} khung · còn ~{eta:.0f}s",
                       preview=preview)
                last_report = now

    try:
        if cfg.merge:
            target = job / "pencil_merged.mp4"
            with VideoWriter(target, cfg, ffmpeg, cancel) as writer:
                for index, path in enumerate(paths):
                    render(path, writer, index)
                report(status="Đang hoàn tất MP4…")
                writer.finish()
            outputs.append(str(target))
        else:
            for index, path in enumerate(paths):
                check_cancel(cancel)
                # Tên ngắn, không phụ thuộc ký tự dành riêng của hệ điều hành.
                stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in path.stem)[:70] or "image"
                target = job / f"{index + 1:03d}_{stem}.mp4"
                with VideoWriter(target, cfg, ffmpeg, cancel) as writer:
                    render(path, writer, index)
                    report(status="Đang hoàn tất MP4…")
                    writer.finish()
                outputs.append(str(target))
        report(progress=1.0, status="Hoàn tất")
        return outputs
    except Cancelled as exc:
        raise Cancelled(outputs) from exc
    except Exception as exc:
        raise BatchError(str(exc), outputs) from exc
    finally:
        # Chỉ xóa thư mục tác vụ nếu nó rỗng; video đã hoàn tất luôn được giữ lại.
        with contextlib.suppress(OSError):
            job.rmdir()


class Mailbox:
    """Tối đa một cập nhật tiến độ/ảnh xem trước, kết quả cuối có hàng đợi riêng."""
    def __init__(self):
        self._lock = threading.Lock()
        self._latest = {}
        self.finished = queue.Queue()

    def report(self, **kwargs):
        with self._lock:
            self._latest.update(kwargs)

    def take(self):
        with self._lock:
            latest, self._latest = self._latest, {}
            return latest


class App:
    def __init__(self, root, config_path: Path, initial_files=()):
        from PIL import ImageTk
        self.ImageTk = ImageTk
        self.root, self.config_path = root, config_path
        self.cancel, self.mailbox = threading.Event(), Mailbox()
        self.worker = None
        self.closing = False
        self.photo = None
        self.files, self.outputs, self.controls = [], [], []
        self.v = {}
        self.root.title(f"{APP_NAME} {VERSION}")
        self.root.geometry("1120x820")
        self.root.minsize(900, 700)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        load_error = None
        try:
            cfg, files, output = load_settings(config_path)
        except ValueError as exc:
            cfg, files, output = RenderConfig(), [], str(Path.home() / "Videos" / "PencilVideoStudio")
            load_error = str(exc)
        self.files = files
        self._build(cfg, output)
        self.add_paths(initial_files)
        self.refresh()
        self.root.after(80, self.poll)
        if load_error:
            self.root.after(100, lambda: messagebox.showwarning(APP_NAME, load_error, parent=self.root))

    def _build(self, cfg, output):
        from tkinter import font as tkfont
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        available_fonts = {name.casefold(): name for name in tkfont.families(self.root)}
        family = next((available_fonts[name.casefold()] for name in ("Segoe UI", "Noto Sans", "DejaVu Sans", "Arial")
                       if name.casefold() in available_fonts), tkfont.nametofont("TkDefaultFont").actual("family"))
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
            tkfont.nametofont(name).configure(family=family, size=10)
        style.configure(".", font=(family, 10))
        style.configure("TButton", padding=(9, 6))
        style.configure("Header.TLabel", font=(family, 19, "bold"))
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)
        ttk.Label(outer, text=APP_NAME, style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(outer, text="Biến ảnh thành video vẽ chì • Xử lý trên máy • MP4/H.264").grid(
            row=1, column=0, sticky="w", pady=(3, 12))
        body = ttk.Panedwindow(outer, orient="horizontal")
        body.grid(row=2, column=0, sticky="nsew")
        left, right = ttk.Frame(body), ttk.Frame(body, padding=(16, 0, 0, 0))
        body.add(left, weight=1)
        body.add(right, weight=2)

        self.tabs = ttk.Notebook(left)
        self.tabs.pack(fill="both", expand=True)
        filebox = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(filebox, text="1. Ảnh đầu vào")
        listing = ttk.Frame(filebox)
        listing.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(listing, height=7, selectmode="extended", exportselection=False)
        scroll = ttk.Scrollbar(listing, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scroll.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        buttons = ttk.Frame(filebox)
        buttons.pack(fill="x", pady=(6, 0))
        for label, command in (("Thêm ảnh", self.choose_files), ("Xóa", self.remove_files),
                               ("↑", lambda: self.move_file(-1)), ("↓", lambda: self.move_file(1))):
            self._button(buttons, label, command).pack(side="left", padx=(0, 4))
        self.count_label = ttk.Label(filebox)
        self.count_label.pack(anchor="w", pady=(6, 0))

        settings = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(settings, text="2. Hiệu ứng & video")
        settings.columnconfigure(1, weight=1)
        preset = next((k for k, size in PRESETS.items() if size == (cfg.width, cfg.height)), next(iter(PRESETS)))
        self._combo(settings, 0, "Khung hình", "preset", PRESETS, preset)
        for row, (label, key, mapping) in enumerate((("Căn ảnh", "fit", FITS), ("Thứ tự vẽ", "order", ORDERS),
                                                     ("Hiệu ứng", "effect", EFFECTS)), 1):
            selected = next(k for k, value in mapping.items() if value == getattr(cfg, key))
            self._combo(settings, row, label, key, mapping, selected)
        for row, (label, key) in enumerate((("Vẽ mỗi ảnh (giây)", "duration"), ("Giữ ảnh cuối (giây)", "hold"),
                                          ("FPS (1–60)", "fps"), ("Tương phản (0.2–3)", "contrast"),
                                          ("Độ mềm (1–30)", "softness"), ("Vân giấy (0–0.3)", "texture")), 4):
            self.v[key] = tk.StringVar(value=str(getattr(cfg, key)))
            ttk.Label(settings, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
            entry = ttk.Entry(settings, textvariable=self.v[key], width=12)
            entry.grid(row=row, column=1, sticky="ew", pady=3)
            self.controls.append((entry, "normal"))
        for row, (label, key) in enumerate((("Hiện bút chì", "show_pencil"), ("Chừa viền an toàn 5%", "safe_margin"),
                                          ("Ghép tất cả ảnh thành một video", "merge")), 10):
            self.v[key] = tk.BooleanVar(value=getattr(cfg, key))
            checkbox = ttk.Checkbutton(settings, text=label, variable=self.v[key])
            checkbox.grid(row=row, column=0, columnspan=2, sticky="w", pady=2)
            self.controls.append((checkbox, "normal"))

        ttk.Label(right, text="Xem trước", font=(family, 12, "bold")).pack(anchor="w")
        self.preview = tk.Label(right, text="Thêm ảnh rồi bấm “Xem trước”.", bg="#e8e4dc", fg="#57534e")
        self.preview.pack(fill="both", expand=True, pady=8)
        self._button(right, "Xem trước ảnh đã chọn", self.show_preview).pack(anchor="w")
        ttk.Label(right, text="Xem trước là ảnh hoàn thiện. Khi xuất, khung hình đang vẽ sẽ xuất hiện tại đây.",
                  wraplength=420).pack(anchor="w", pady=8)

        output_box = ttk.LabelFrame(outer, text="3. Xuất video", padding=8)
        output_box.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.v["out"] = tk.StringVar(value=output)
        entry = ttk.Entry(output_box, textvariable=self.v["out"])
        entry.pack(side="left", fill="x", expand=True)
        self.controls.append((entry, "normal"))
        self._button(output_box, "Chọn thư mục", self.choose_output).pack(side="left", padx=6)
        self.btn_open = ttk.Button(output_box, text="Mở thư mục", command=self.open_output)
        self.btn_open.pack(side="left")
        actions = ttk.Frame(outer)
        actions.grid(row=4, column=0, sticky="ew", pady=10)
        self.btn_start = ttk.Button(actions, text="Xuất MP4", command=self.start)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(actions, text="Dừng", command=self.stop, state="disabled")
        self.btn_stop.pack(side="left", padx=8)
        self.prog = ttk.Progressbar(actions, maximum=100)
        self.prog.pack(side="left", fill="x", expand=True)
        self.status = ttk.Label(outer, text="Sẵn sàng", wraplength=1000)
        self.status.grid(row=5, column=0, sticky="w")

    def _button(self, parent, text, command):
        button = ttk.Button(parent, text=text, command=command)
        self.controls.append((button, "normal"))
        return button

    def _combo(self, parent, row, label, key, choices, value):
        self.v[key] = tk.StringVar(value=value)
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        widget = ttk.Combobox(parent, textvariable=self.v[key], values=list(choices), state="readonly", width=27)
        widget.grid(row=row, column=1, sticky="ew", pady=3)
        self.controls.append((widget, "readonly"))

    def busy(self):
        return self.worker is not None

    def add_paths(self, paths):
        seen = {os.path.normcase(str(Path(f).resolve())) for f in self.files}
        for file in paths:
            path = Path(file).expanduser().resolve()
            key = os.path.normcase(str(path))
            if path.is_file() and key not in seen and len(self.files) < MAX_FILES:
                self.files.append(str(path))
                seen.add(key)
        self.refresh()

    def choose_files(self):
        if self.busy():
            return
        paths = filedialog.askopenfilenames(parent=self.root, title="Chọn ảnh",
                  filetypes=[("Ảnh", "*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff *.gif"), ("Tất cả", "*")])
        self.add_paths(paths)

    def refresh(self):
        self.listbox.delete(0, "end")
        for index, file in enumerate(self.files, 1):
            self.listbox.insert("end", f"{index:02d}. {Path(file).name}")
        self.count_label.configure(text=f"{len(self.files)}/{MAX_FILES} ảnh • Chọn một ảnh để đổi thứ tự")

    def remove_files(self):
        if self.busy():
            return
        for index in reversed(self.listbox.curselection()):
            del self.files[index]
        self.refresh()

    def move_file(self, direction):
        selected = self.listbox.curselection()
        if self.busy() or len(selected) != 1:
            return
        index = selected[0]
        other = index + direction
        if 0 <= other < len(self.files):
            self.files[index], self.files[other] = self.files[other], self.files[index]
            self.refresh()
            self.listbox.selection_set(other)
            self.listbox.see(other)

    def choose_output(self):
        path = filedialog.askdirectory(parent=self.root, title="Thư mục xuất video")
        if path:
            self.v["out"].set(path)

    def open_output(self):
        path = Path(self.outputs[-1]).parent if self.outputs else Path(self.v["out"].get()).expanduser()
        if not path.is_dir():
            messagebox.showinfo(APP_NAME, "Thư mục chưa tồn tại. Hãy xuất video trước.", parent=self.root)
            return
        try:
            if sys.platform == "win32":
                os.startfile(path)
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Không mở được thư mục: {exc}", parent=self.root)

    def get_cfg(self):
        try:
            width, height = PRESETS[self.v["preset"].get()]
            return RenderConfig(width=width, height=height, fps=int(self.v["fps"].get()),
                duration=float(self.v["duration"].get()), hold=float(self.v["hold"].get()),
                fit=FITS[self.v["fit"].get()], order=ORDERS[self.v["order"].get()],
                effect=EFFECTS[self.v["effect"].get()], contrast=float(self.v["contrast"].get()),
                softness=float(self.v["softness"].get()), texture=float(self.v["texture"].get()),
                safe_margin=self.v["safe_margin"].get(), show_pencil=self.v["show_pencil"].get(),
                merge=self.v["merge"].get()).validate()
        except (ValueError, KeyError, tk.TclError) as exc:
            raise ValueError(f"Thông số không hợp lệ: {exc}") from exc

    def set_busy(self, busy):
        for widget, enabled_state in self.controls:
            widget.configure(state="disabled" if busy else enabled_state)
        self.btn_start.configure(state="disabled" if busy else "normal")
        self.btn_stop.configure(state="normal" if busy else "disabled")

    def _launch(self, work):
        self.cancel.clear()
        self.mailbox = Mailbox()
        self.prog["value"] = 0
        self.set_busy(True)
        self.status.configure(text="Đang chuẩn bị…")

        def wrapped():
            try:
                result = work()
                self.mailbox.finished.put(("ok", result))
            except Cancelled as exc:
                self.mailbox.finished.put(("cancel", exc))
            except Exception as exc:
                LOG.exception("Tác vụ thất bại")
                self.mailbox.finished.put(("error", exc))

        self.worker = threading.Thread(target=wrapped, name="pencil-render", daemon=False)
        self.worker.start()

    def start(self):
        if self.busy():
            return
        if not self.files:
            messagebox.showinfo(APP_NAME, "Hãy thêm ít nhất một ảnh.", parent=self.root)
            return
        try:
            cfg = self.get_cfg()
            output = self.v["out"].get().strip()
            if not output:
                raise ValueError("Hãy chọn thư mục xuất.")
        except ValueError as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=self.root)
            return
        try:
            save_settings(self.config_path, cfg, list(self.files), output)
        except OSError as exc:
            messagebox.showwarning(APP_NAME, f"Không lưu được cấu hình; vẫn tiếp tục xuất video.\n{exc}", parent=self.root)
        files = list(self.files)
        self._launch(lambda: run_batch(files, cfg, output, self.cancel, self.mailbox.report))

    def show_preview(self):
        if self.busy() or not self.files:
            return
        try:
            cfg = self.get_cfg()
        except ValueError as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=self.root)
            return
        selected = self.listbox.curselection()
        path = self.files[selected[0] if selected else 0]
        scale = min(640 / cfg.width, 480 / cfg.height, 1)
        preview_cfg = replace(cfg, width=max(16, int(cfg.width * scale) // 2 * 2),
                              height=max(16, int(cfg.height * scale) // 2 * 2),
                              softness=max(1, cfg.softness * scale))

        def work():
            renderer = PencilRenderer(Path(path), preview_cfg, self.cancel)
            self.mailbox.report(preview=renderer.frame(1), status="Xem trước đã sẵn sàng")
            return None
        self._launch(work)

    def stop(self):
        if self.busy():
            self.cancel.set()
            self.btn_stop.configure(state="disabled")
            self.status.configure(text="Đang dừng và dọn tệp chưa hoàn tất…")

    def poll(self):
        updates = self.mailbox.take()
        if "progress" in updates:
            self.prog["value"] = updates["progress"] * 100
        if "status" in updates and not self.cancel.is_set():
            self.status.configure(text=updates["status"])
        if "preview" in updates and not self.closing:
            self.photo = self.ImageTk.PhotoImage(updates["preview"])
            self.preview.configure(image=self.photo, text="")
        # Chờ luồng thực sự kết thúc trước khi cho khởi chạy tác vụ tiếp theo.
        if self.worker is not None and not self.worker.is_alive():
            self.worker.join()
            self.worker = None
            self.set_busy(False)
            try:
                kind, data = self.mailbox.finished.get_nowait()
            except queue.Empty:
                kind, data = "error", RuntimeError("Tác vụ kết thúc nhưng không trả kết quả.")
            if self.closing:
                self.root.destroy()
                return
            if kind == "ok" and data is not None:
                self.outputs = data
                self.status.configure(text=f"Đã xuất {len(data)} video • {Path(data[-1]).parent}")
                messagebox.showinfo(APP_NAME, f"Đã xuất {len(data)} video.\nThư mục: {Path(data[-1]).parent}", parent=self.root)
            elif kind == "cancel":
                self.outputs = data.outputs
                self.status.configure(text=f"Đã dừng • Giữ lại {len(self.outputs)} video đã hoàn tất")
            elif kind == "error":
                self.outputs = getattr(data, "outputs", [])
                self.status.configure(text="Xuất thất bại — xem thông báo lỗi")
                extra = f"\nGiữ lại {len(self.outputs)} video tại {Path(self.outputs[-1]).parent}" if self.outputs else ""
                messagebox.showerror(APP_NAME, str(data) + extra, parent=self.root)
        self.root.after(80, self.poll)

    def on_close(self):
        if self.closing:
            return
        if self.busy():
            if not messagebox.askyesno(APP_NAME, "Tác vụ đang chạy. Dừng tác vụ và đóng ứng dụng?", parent=self.root):
                return
            self.closing = True
            self.stop()
        else:
            try:
                save_settings(self.config_path, self.get_cfg(), list(self.files), self.v["out"].get())
            except (ValueError, OSError) as exc:
                LOG.warning("Không lưu được cấu hình khi đóng: %s", exc)
            self.root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Tạo video vẽ chì từ ảnh — giao diện hoặc dòng lệnh.")
    parser.add_argument("files", nargs="*", help="Đường dẫn ảnh đầu vào")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION}")
    parser.add_argument("--headless", action="store_true", help="Xuất không cần giao diện")
    parser.add_argument("--config", type=Path, default=settings_path(), help="Tệp cấu hình giao diện")
    parser.add_argument("--output", type=Path, default=Path("pencil_output"))
    parser.add_argument("--size", default="1280x720", help="Rộng x cao, số chẵn, tối đa 1920 mỗi chiều")
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--duration", type=float, default=8, help="Thời gian vẽ mỗi ảnh (giây)")
    parser.add_argument("--hold", type=float, default=2, help="Thời gian giữ ảnh cuối (giây)")
    parser.add_argument("--fit", choices=FITS.values(), default="contain")
    parser.add_argument("--order", choices=ORDERS.values(), default="horizontal")
    parser.add_argument("--effect", choices=EFFECTS.values(), default="pencil")
    parser.add_argument("--contrast", type=float, default=1.2)
    parser.add_argument("--softness", type=float, default=8)
    parser.add_argument("--texture", type=float, default=0.08)
    parser.add_argument("--merge", action="store_true")
    parser.add_argument("--no-pencil", action="store_true")
    parser.add_argument("--safe-margin", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if not args.headless:
        if tk is None:
            parser.exit(1, "Thiếu Tkinter. Linux: cài python3-tk; Windows/macOS: dùng Python có Tkinter.\n")
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            parser.exit(1, f"Không mở được giao diện: {exc}\nDùng --headless trên máy không có màn hình.\n")
        App(root, args.config, args.files)
        root.mainloop()
        return 0
    cancel = threading.Event()
    old_sigint = signal.getsignal(signal.SIGINT)
    old_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, lambda *_: cancel.set())
    signal.signal(signal.SIGTERM, lambda *_: cancel.set())
    try:
        size = args.size.lower().split("x")
        if len(size) != 2:
            raise ValueError("--size phải có dạng 1280x720.")
        cfg = RenderConfig(width=int(size[0]), height=int(size[1]), fps=args.fps, duration=args.duration,
            hold=args.hold, fit=args.fit, order=args.order, effect=args.effect, contrast=args.contrast,
            softness=args.softness, texture=args.texture, merge=args.merge,
            show_pencil=not args.no_pencil, safe_margin=args.safe_margin).validate()

        def report(**kwargs):
            if "status" in kwargs:
                print(kwargs["status"], file=sys.stderr, flush=True)

        outputs = run_batch(args.files, cfg, args.output, cancel, report)
        print("\n".join(outputs))
        return 0
    except Cancelled as exc:
        print(str(exc), file=sys.stderr)
        if exc.outputs:
            print("\n".join(exc.outputs))
        return 130
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Lỗi: {exc}", file=sys.stderr)
        outputs = getattr(exc, "outputs", [])
        if outputs:
            print("Video đã hoàn tất:\n" + "\n".join(outputs), file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGINT, old_sigint)
        signal.signal(signal.SIGTERM, old_sigterm)


if __name__ == "__main__":
    raise SystemExit(main())
