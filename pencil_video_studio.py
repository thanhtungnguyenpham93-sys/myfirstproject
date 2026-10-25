#!/usr/bin/env python3
"""Pencil Video Studio — ảnh → video vẽ chì, với Tkinter hoặc dòng lệnh.

Python >= 3.11; cài requirements.txt và chạy model_assets.py một lần.
Nhận diện AI chạy trên máy. Bản Windows đóng gói kèm mô hình và FFmpeg.
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
    from drawing_engine import StrokeRenderer, PENCILS, PRIORITIES, DETECTORS
except ImportError as exc:
    raise SystemExit("Thiếu thư viện. Chạy Setup-Windows.bat hoặc python -m pip install -r requirements.txt") from exc

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:
    tk = None

APP_NAME = "Pencil Video Studio"
VERSION = "3.0.0"
LOG = logging.getLogger(__name__)
MAX_FILES = 200
Image.MAX_IMAGE_PIXELS = 40_000_000
PRESETS = {
    "YouTube · 1920 × 1080 · 30fps": (1920, 1080),
    "TikTok / Reels / Shorts · 1080 × 1920": (1080, 1920),
    "Facebook Feed · 1080 × 1350": (1080, 1350),
    "Facebook vuông · 1080 × 1080": (1080, 1080),
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
    fps: int = 30
    duration: float = 0.0
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
    pencil_type: str = "hb"
    pen_size: float = 95.0
    line_width: float = 1.3
    pen_speed: float = 1.0
    fill_speed: float = 2.5
    detail: float = 0.7
    smoothness: float = 0.8
    priority: str = "subject_background_text"
    subject_detection: str = "ai"
    detect_text: bool = True
    face_priority: bool = True
    camera: float = 0.025
    vignette: float = 0.06
    transition: float = 0.35
    platform: str = "custom"

    def validate(self):
        for name in ("width", "height", "fps"):
            value = getattr(self, name)
            if type(value) is not int:
                raise ValueError(f"{name} phải là số nguyên.")
        if not all(16 <= v <= 1920 and v % 2 == 0 for v in (self.width, self.height)):
            raise ValueError("Chiều rộng/cao phải là số chẵn từ 16 đến 1920.")
        if not 1 <= self.fps <= 60:
            raise ValueError("FPS phải nằm trong khoảng 1–60.")
        limits = {"duration": (0, 600), "hold": (0, 120), "contrast": (0.2, 3),
                  "softness": (1, 30), "texture": (0, 0.3), "pen_size": (20, 200),
                  "line_width": (0.4, 6), "pen_speed": (0.25, 4), "fill_speed": (0.5, 6),
                  "detail": (0, 1), "smoothness": (0, 1), "camera": (0, 0.08),
                  "vignette": (0, 0.3), "transition": (0, 2)}
        for name, (low, high) in limits.items():
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
                raise ValueError(f"{name} phải là số hữu hạn.")
            if not low <= value <= high:
                raise ValueError(f"{name} phải nằm trong khoảng {low}–{high}.")
        for name, choices in (("fit", FITS.values()), ("order", ORDERS.values()), ("effect", EFFECTS.values()),
                              ("pencil_type", PENCILS.values()), ("priority", PRIORITIES.values()),
                              ("subject_detection", DETECTORS.values()),
                              ("platform", ("custom", "youtube", "vertical", "facebook"))):
            if getattr(self, name) not in choices:
                raise ValueError(f"Giá trị {name} không hợp lệ.")
        for name in ("safe_margin", "show_pencil", "merge", "detect_text", "face_priority"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} phải là true hoặc false.")
        return self

    @property
    def draw_frames(self):
        # Auto duration (duration=0) is resolved by StrokeRenderer after tracing.
        return max(2, round((self.duration or 12) / self.pen_speed * self.fps))

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
    data = {"version": 3, "render": asdict(cfg), "files": files, "output": output}
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
        if not isinstance(data, dict) or data.get("version") not in (2, 3):
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
    executable = None if getattr(sys, "frozen", False) else shutil.which("ffmpeg")
    if not executable:
        try:
            import imageio_ffmpeg
            executable = imageio_ffmpeg.get_ffmpeg_exe()
        except (ImportError, RuntimeError) as exc:
            raise RuntimeError("Không tìm thấy FFmpeg đi kèm. Chạy lại Setup-Windows.bat hoặc cài FFmpeg vào PATH.") from exc
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
        left = right = top = bottom = margin
        if cfg.safe_margin and cfg.platform == "vertical":
            left, right, top, bottom = 0.06, 0.14, 0.08, 0.18
        elif cfg.safe_margin and cfg.platform == "youtube":
            bottom = 0.08
        box = (max(1, round(cfg.width * (1 - left - right))), max(1, round(cfg.height * (1 - top - bottom))))
        fit = ImageOps.contain if cfg.fit == "contain" else ImageOps.fit
        scaled = fit(rgb, box, method=Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (cfg.width, cfg.height), "white")
        canvas.paste(scaled, (round(cfg.width * left) + (box[0] - scaled.width) // 2,
                              round(cfg.height * top) + (box[1] - scaled.height) // 2))
        return canvas
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise ValueError(f"Không đọc được ảnh '{path.name}': {exc}") from exc


class PencilRenderer(StrokeRenderer):
    def __init__(self, path, cfg, cancel, report=lambda **kw: None):
        cfg.validate()
        check_cancel(cancel)
        super().__init__(load_image(Path(path), cfg), cfg, lambda: check_cancel(cancel), report)


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
    previous_final = None

    def render(path, writer, index):
        nonlocal done, last_report, previous_final
        report(status=f"Chuẩn bị ảnh {index + 1}/{len(paths)}: {path.name}")
        renderer = PencilRenderer(path, cfg, cancel, report)
        if cfg.merge and index and cfg.transition > 0:
            next_paper = renderer.frame(0, 0)
            transition_frames = max(1, round(cfg.transition * cfg.fps))
            for i in range(transition_frames):
                check_cancel(cancel)
                t = (i + 1) / transition_frames
                writer.write(Image.blend(previous_final, next_paper, t * t * (3 - 2 * t)))
        for frame_index in range(renderer.frame_count):
            check_cancel(cancel)
            progress = min(1, frame_index / (renderer.draw_frames - 1))
            scene_progress = frame_index / max(1, renderer.frame_count - 1)
            frame = renderer.frame(progress, scene_progress)
            writer.write(frame)
            done += 1
            now = time.monotonic()
            if now - last_report >= 0.25 or frame_index == renderer.frame_count - 1:
                overall = (index + (frame_index + 1) / renderer.frame_count) / len(paths)
                elapsed = now - started
                eta = elapsed * (1 - overall) / overall
                preview = frame.copy()
                preview.thumbnail((640, 480), Image.Resampling.LANCZOS)
                report(progress=overall,
                       status=f"Ảnh {index + 1}/{len(paths)} · {frame_index + 1}/{renderer.frame_count} khung · còn ~{eta:.0f}s",
                       preview=preview)
                last_report = now
        previous_final = frame

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
        self.preview_source = None
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
        self.tabs.add(settings, text="2. Thiết lập vẽ")
        self.settings_tabs = ttk.Notebook(settings)
        self.settings_tabs.pack(fill="both", expand=True)
        pages = {}
        for key, title in (("video", "Video"), ("pencil", "Bút & nét"), ("regions", "Chủ thể & chữ"), ("look", "Điện ảnh")):
            page = ttk.Frame(self.settings_tabs, padding=10)
            page.columnconfigure(1, weight=1)
            self.settings_tabs.add(page, text=title)
            pages[key] = page
        preset = next((k for k, size in PRESETS.items() if size == (cfg.width, cfg.height)
                       and not k.startswith(("YouTube", "TikTok", "Facebook"))), next(iter(PRESETS)))
        if cfg.platform != "custom":
            preset = next((k for k, size in PRESETS.items() if size == (cfg.width, cfg.height)), preset)
        self.platform = cfg.platform
        self._combo(pages["video"], 0, "Nền tảng / khung", "preset", PRESETS, preset).bind("<<ComboboxSelected>>", self.apply_preset)
        self._combo(pages["video"], 1, "Căn ảnh", "fit", FITS, next(k for k,v in FITS.items() if v == cfg.fit))
        self._combo(pages["pencil"], 0, "Loại bút", "pencil_type", PENCILS, next(k for k,v in PENCILS.items() if v == cfg.pencil_type))
        self._combo(pages["regions"], 0, "Tách chủ thể", "subject_detection", DETECTORS,
                    next(k for k,v in DETECTORS.items() if v == cfg.subject_detection))
        self._combo(pages["regions"], 1, "Thứ tự vẽ", "priority", PRIORITIES,
                    next(k for k,v in PRIORITIES.items() if v == cfg.priority))
        self._combo(pages["look"], 0, "Sắc độ", "effect", EFFECTS, next(k for k,v in EFFECTS.items() if v == cfg.effect))
        numbers = {
            "video": [(2, "Thời gian vẽ (0=tự động)", "duration"), (3, "Giữ tranh cuối (giây)", "hold"),
                      (4, "FPS (1–60)", "fps")],
            "pencil": [(1, "Cỡ bút hiển thị (20–200)", "pen_size"), (2, "Độ dày nét (0.4–6)", "line_width"),
                       (3, "Tốc độ bút (0.25–4×)", "pen_speed"), (4, "Tốc độ đánh bóng (0.5–6×)", "fill_speed"),
                       (5, "Mức chi tiết (0–1)", "detail"), (6, "Độ uốn mềm (0–1)", "smoothness")],
            "look": [(1, "Tương phản (0.2–3)", "contrast"), (2, "Độ mềm sắc độ (1–30)", "softness"),
                     (3, "Vân giấy (0–0.3)", "texture"), (4, "Zoom chậm (0–0.08)", "camera"),
                     (5, "Tối viền (0–0.3)", "vignette"), (6, "Chuyển ảnh khi ghép (giây)", "transition")],
        }
        for page, items in numbers.items():
            for row, label, key in items:
                self.v[key] = tk.StringVar(value=str(getattr(cfg, key)))
                ttk.Label(pages[page], text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=6)
                entry = ttk.Entry(pages[page], textvariable=self.v[key], width=10)
                entry.grid(row=row, column=1, sticky="ew", pady=6)
                self.controls.append((entry, "normal"))
        checks = (("video", 5, "Chừa vùng an toàn theo nền tảng", "safe_margin"),
                  ("video", 6, "Ghép tất cả ảnh thành một video", "merge"),
                  ("pencil", 7, "Hiện bút chuyển động theo nét", "show_pencil"),
                  ("regions", 2, "Tự nhận diện và tách vùng chữ", "detect_text"),
                  ("regions", 3, "Ưu tiên chi tiết khuôn mặt", "face_priority"))
        for page, row, label, key in checks:
            self.v[key] = tk.BooleanVar(value=getattr(cfg, key))
            checkbox = ttk.Checkbutton(pages[page], text=label, variable=self.v[key])
            checkbox.grid(row=row, column=0, columnspan=2, sticky="w", pady=6)
            self.controls.append((checkbox, "normal"))
        ttk.Label(pages["regions"], text="Xem vùng trước khi xuất: xanh lá = chủ thể, vàng = chữ, xanh dương = khuôn mặt. "
                  "AI có thể nhầm trên ảnh phức tạp; bạn có thể đổi chế độ và thứ tự vẽ.",
                  wraplength=390).grid(row=4, column=0, columnspan=2, sticky="w", pady=14)
        ttk.Label(pages["video"], text="Thời gian 0: tự tính theo số nét. Tăng tốc độ bút sẽ rút ngắn thời gian vẽ. "
                  "Giữ toàn ảnh giúp không cắt mất người hoặc chữ.", wraplength=390).grid(
                      row=7, column=0, columnspan=2, sticky="w", pady=14)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        ttk.Label(right, text="Xưởng vẽ · xem trước", font=(family, 12, "bold")).grid(row=0, column=0, sticky="w")
        self.preview = tk.Label(right, text="Thêm ảnh rồi chọn một chế độ xem trước.", bg="#eee9df", fg="#57534e")
        self.preview.grid(row=1, column=0, sticky="nsew", pady=8)
        self.preview.bind("<Configure>", lambda event: self.fit_preview())
        preview_buttons = ttk.Frame(right)
        preview_buttons.grid(row=2, column=0, sticky="ew")
        for label, mode in (("Xem tranh", "image"), ("Xem vùng", "regions"), ("Vẽ thử 6s", "animation")):
            self._button(preview_buttons, label, lambda value=mode: self.show_preview(value)).pack(side="left", padx=(0, 4))
        self.analysis_label = ttk.Label(right, text="Nhận diện và dựng nét chạy ngay trên máy, không gửi ảnh lên mạng.",
                                        wraplength=440)
        self.analysis_label.grid(row=3, column=0, sticky="w", pady=8)

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

    def fit_preview(self, image=None):
        if image is not None:
            self.preview_source = image.copy()
        width, height = self.preview.winfo_width(), self.preview.winfo_height()
        if self.preview_source is not None and width > 4 and height > 4:
            fitted = self.preview_source.copy()
            fitted.thumbnail((width - 4, height - 4), Image.Resampling.LANCZOS)
            self.photo = self.ImageTk.PhotoImage(fitted)
            self.preview.configure(image=self.photo, text="")
        if hasattr(self, "analysis_label"):
            self.analysis_label.configure(wraplength=max(200, width))

    def _combo(self, parent, row, label, key, choices, value):
        self.v[key] = tk.StringVar(value=value)
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        widget = ttk.Combobox(parent, textvariable=self.v[key], values=list(choices), state="readonly", width=27)
        widget.grid(row=row, column=1, sticky="ew", pady=3)
        self.controls.append((widget, "readonly"))
        return widget

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

    def apply_preset(self, event=None):
        label = self.v["preset"].get()
        self.platform = ("youtube" if label.startswith("YouTube") else
                         "vertical" if label.startswith("TikTok") else
                         "facebook" if label.startswith("Facebook") else "custom")
        if self.platform != "custom":
            self.v["fps"].set("30")
            self.v["fit"].set(next(k for k,v in FITS.items() if v == "contain"))
            self.v["safe_margin"].set(True)

    def get_cfg(self):
        try:
            width, height = PRESETS[self.v["preset"].get()]
            values = dict(width=width, height=height, platform=self.platform, fps=int(self.v["fps"].get()))
            for key in ("duration", "hold", "contrast", "softness", "texture", "pen_size", "line_width",
                        "pen_speed", "fill_speed", "detail", "smoothness", "camera", "vignette", "transition"):
                values[key] = float(self.v[key].get())
            for key in ("safe_margin", "show_pencil", "merge", "detect_text", "face_priority"):
                values[key] = self.v[key].get()
            for key, mapping in (("fit", FITS), ("effect", EFFECTS), ("pencil_type", PENCILS),
                                 ("priority", PRIORITIES), ("subject_detection", DETECTORS)):
                values[key] = mapping[self.v[key].get()]
            return RenderConfig(**values).validate()
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

    def show_preview(self, mode="image"):
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
            renderer = PencilRenderer(Path(path), preview_cfg, self.cancel, self.mailbox.report)
            if mode == "regions":
                self.mailbox.report(preview=renderer.analysis_preview())
            elif mode == "animation":
                for index in range(73):
                    check_cancel(self.cancel)
                    started = time.monotonic()
                    self.mailbox.report(preview=renderer.frame(index / 72), progress=index / 72)
                    self.cancel.wait(max(0, 1 / 12 - (time.monotonic() - started)))
                check_cancel(self.cancel)
            else:
                self.mailbox.report(preview=renderer.frame(1))
            self.mailbox.report(status="Xem trước đã sẵn sàng")
            return None
        self._launch(work)

    def stop(self):
        if self.busy():
            self.cancel.set()
            self.btn_stop.configure(state="disabled")
            self.status.configure(text="Đang dừng và dọn tệp chưa hoàn tất…")

    def poll(self):
        updates = self.mailbox.take()
        if "notes" in updates:
            self.analysis_label.configure(text=" ".join(updates["notes"]))
        if "progress" in updates:
            self.prog["value"] = updates["progress"] * 100
        if "status" in updates and not self.cancel.is_set():
            self.status.configure(text=updates["status"])
        if "preview" in updates and not self.closing:
            self.fit_preview(updates["preview"])
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


def self_test(output):
    """Exercise bundled native libraries, both model sessions, and video encoding."""
    from PIL import ImageFont
    import traceback
    folder = Path(output).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    try:
        source = folder / "self-test-input.png"
        picture = Image.new("RGB", (384, 288), "white")
        draw = ImageDraw.Draw(picture)
        draw.ellipse((125, 35, 255, 175), fill="#9b6950", outline="#242424", width=3)
        draw.rectangle((140, 175, 240, 230), fill="#557e9a")
        draw.text((40, 240), "PENCIL STUDIO", fill="black", font=ImageFont.load_default(size=30))
        picture.save(source)
        cfg = RenderConfig(width=384, height=288, fps=10, duration=0.6, hold=0.2,
                           camera=0, vignette=0, show_pencil=False)
        cancel = threading.Event()
        renderer = PencilRenderer(source, cfg, cancel)
        if not renderer.regions.text_boxes:
            raise RuntimeError("Kiểm tra mô hình chữ thất bại: không phát hiện chữ trong ảnh mẫu.")
        if not renderer.strokes:
            raise RuntimeError("Không tạo được đường nét.")
        outputs = run_batch([source], cfg, folder / "video", cancel)
        decoded = subprocess.run([find_ffmpeg(), "-v", "error", "-i", outputs[0], "-f", "rawvideo",
                                  "-pix_fmt", "rgb24", "pipe:1"], capture_output=True, timeout=60,
                                  **subprocess_options())
        expected = cfg.frame_count * cfg.width * cfg.height * 3
        if decoded.returncode or len(decoded.stdout) != expected:
            raise RuntimeError("Không giải mã được đủ khung hình MP4 vừa xuất.")
        result = {"status": "passed", "version": VERSION, "frames": cfg.frame_count,
                  "strokes": len(renderer.strokes), "text_regions": len(renderer.regions.text_boxes),
                  "subject_model": "u2netp", "ffmpeg": find_ffmpeg(), "videos": outputs}
        (folder / "self-test.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0
    except Exception:
        (folder / "self-test-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="Tạo video vẽ chì từ ảnh — giao diện hoặc dòng lệnh.")
    parser.add_argument("files", nargs="*", help="Đường dẫn ảnh đầu vào")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION}")
    parser.add_argument("--headless", action="store_true", help="Xuất không cần giao diện")
    parser.add_argument("--self-test", action="store_true", help="Kiểm tra bản đóng gói, mô hình và FFmpeg")
    parser.add_argument("--config", type=Path, default=settings_path(), help="Tệp cấu hình giao diện")
    parser.add_argument("--output", type=Path, default=Path("pencil_output"))
    parser.add_argument("--size", default=None, help="Rộng x cao; bỏ trống để theo --platform")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--duration", type=float, default=0, help="Thời gian vẽ; 0=tự tính theo chi tiết")
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
    parser.add_argument("--pencil-type", choices=PENCILS.values(), default="hb")
    parser.add_argument("--pen-size", type=float, default=95)
    parser.add_argument("--line-width", type=float, default=1.3)
    parser.add_argument("--pen-speed", type=float, default=1)
    parser.add_argument("--fill-speed", type=float, default=2.5)
    parser.add_argument("--detail", type=float, default=0.7)
    parser.add_argument("--smoothness", type=float, default=0.8)
    parser.add_argument("--priority", choices=PRIORITIES.values(), default="subject_background_text")
    parser.add_argument("--subject-detection", choices=DETECTORS.values(), default="ai")
    parser.add_argument("--no-text", action="store_true")
    parser.add_argument("--no-face", action="store_true")
    parser.add_argument("--camera", type=float, default=0.025)
    parser.add_argument("--vignette", type=float, default=0.06)
    parser.add_argument("--transition", type=float, default=0.35)
    parser.add_argument("--platform", choices=("custom", "youtube", "vertical", "facebook"), default="custom")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if args.self_test:
        return self_test(args.output)
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
        default_sizes = {"custom": "1280x720", "youtube": "1920x1080", "vertical": "1080x1920", "facebook": "1080x1350"}
        size = (args.size or default_sizes[args.platform]).lower().split("x")
        if len(size) != 2:
            raise ValueError("--size phải có dạng 1280x720.")
        cfg = RenderConfig(width=int(size[0]), height=int(size[1]), fps=args.fps, duration=args.duration,
            hold=args.hold, fit=args.fit, order=args.order, effect=args.effect, contrast=args.contrast,
            softness=args.softness, texture=args.texture, merge=args.merge,
            show_pencil=not args.no_pencil, safe_margin=args.safe_margin or args.platform != "custom", pencil_type=args.pencil_type,
            pen_size=args.pen_size, line_width=args.line_width, pen_speed=args.pen_speed, fill_speed=args.fill_speed,
            detail=args.detail, smoothness=args.smoothness, priority=args.priority,
            subject_detection=args.subject_detection, detect_text=not args.no_text, face_priority=not args.no_face,
            camera=args.camera, vignette=args.vignette, transition=args.transition, platform=args.platform).validate()

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
