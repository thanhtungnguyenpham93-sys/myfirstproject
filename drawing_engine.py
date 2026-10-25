"""Semantic regions, smooth vector strokes, pressure, and incremental pencil rendering.

No network requests are made while processing an image. U²-Net and the text
detector run locally. All masks and paths share the fitted image coordinates.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import threading

import cv2
import numpy as np
from PIL import Image

from model_assets import model_path, verify_model

cv2.setNumThreads(2)

PENCILS = {
    "2H · mảnh, sáng": "2h",
    "HB · cân bằng": "hb",
    "2B · mềm, đậm": "2b",
    "6B · đậm, giàu sắc độ": "6b",
    "Than chì · mềm, có hạt": "charcoal",
}
STYLES = {
    "2h": (0.7, 0.65, 0.35),
    "hb": (0.9, 0.9, 0.5),
    "2b": (1.05, 1.1, 0.7),
    "6b": (1.2, 1.4, 1.0),
    "charcoal": (1.1, 1.7, 1.5),
}
PRIORITIES = {
    "Chủ thể → nền → chữ": "subject_background_text",
    "Chủ thể → chữ → nền": "subject_text_background",
    "Chữ → chủ thể → nền": "text_subject_background",
    "Nền → chủ thể → chữ": "background_subject_text",
    "Không chia vùng, vẽ từ trên xuống": "natural",
}
DETECTORS = {"AI tự tách chủ thể": "ai", "Vùng trung tâm (không AI)": "center", "Không tách chủ thể": "none"}


@dataclass
class Regions:
    subject: np.ndarray
    text: np.ndarray
    faces: np.ndarray
    text_boxes: list
    notes: list[str]

    @property
    def labels(self):
        result = np.zeros(self.subject.shape, np.uint8)
        result[self.subject] = 1
        result[self.text] = 2
        return result


class LocalModels:
    """Sessions are reused across a batch. GUI permits one worker at a time."""
    _subject = None
    _ocr = None
    _lock = threading.Lock()

    @classmethod
    def subject(cls, rgb):
        import onnxruntime as ort
        ort.disable_telemetry_events()
        with cls._lock:
            if cls._subject is None:
                path = model_path()
                if not path.is_file():
                    raise RuntimeError("Chưa có mô hình chủ thể. Chạy Setup-Windows.bat hoặc python model_assets.py; "
                                       "có thể chọn 'Vùng trung tâm' để chạy không AI.")
                verify_model(path)
                options = ort.SessionOptions()
                options.intra_op_num_threads = 2
                options.inter_op_num_threads = 1
                cls._subject = ort.InferenceSession(str(path), sess_options=options,
                                                    providers=["CPUExecutionProvider"])
        small = cv2.resize(rgb, (320, 320), interpolation=cv2.INTER_AREA).astype(np.float32)
        small /= max(float(small.max()), 1.0)
        small = (small - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
        tensor = np.transpose(small, (2, 0, 1))[None].astype(np.float32)
        session = cls._subject
        prediction = session.run([session.get_outputs()[0].name], {session.get_inputs()[0].name: tensor})[0][0, 0]
        prediction = (prediction - prediction.min()) / max(float(np.ptp(prediction)), 1e-6)
        return cv2.resize(prediction, (rgb.shape[1], rgb.shape[0]), interpolation=cv2.INTER_LINEAR)

    @classmethod
    def text(cls, rgb):
        with cls._lock:
            if cls._ocr is None:
                from rapidocr_onnxruntime import RapidOCR
                cls._ocr = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1,
                                    use_cls=False, use_rec=False, det_limit_side_len=736,
                                    det_limit_type="max")
        # Detector only: original letter shapes are traced, never replaced by a font.
        boxes, _ = cls._ocr(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), use_cls=False, use_rec=False)
        return [] if boxes is None else [np.asarray(box, np.float32) for box in boxes]


def analyze_regions(rgb, cfg, check):
    check()
    h, w = rgb.shape[:2]
    notes = []
    subject = np.zeros((h, w), bool)
    if cfg.subject_detection == "ai":
        subject = LocalModels.subject(rgb) > 0.45
        coverage = float(subject.mean())
        if coverage < 0.005 or coverage > 0.98:
            notes.append("AI chưa tách rõ chủ thể ở ảnh này; xem bản đồ vùng và cân nhắc chế độ trung tâm.")
    elif cfg.subject_detection == "center":
        y, x = np.ogrid[:h, :w]
        subject = ((x - w / 2) / (w * 0.32)) ** 2 + ((y - h / 2) / (h * 0.43)) ** 2 < 1
        notes.append("Chủ thể được chọn theo vùng trung tâm, không dùng AI.")
    check()
    text = np.zeros((h, w), np.uint8)
    boxes = LocalModels.text(rgb) if cfg.detect_text else []
    for box in boxes:
        cv2.fillPoly(text, [np.rint(box).astype(np.int32)], 255)
    if boxes:
        text = cv2.dilate(text, np.ones((3, 3), np.uint8))
    notes.append(f"Nhận diện {len(boxes)} vùng chữ." if cfg.detect_text else "Nhận diện chữ đang tắt.")
    check()
    faces = np.zeros((h, w), np.uint8)
    if cfg.face_priority:
        detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        if detector.empty():
            raise RuntimeError("Thiếu dữ liệu nhận diện khuôn mặt trong bản cài OpenCV.")
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        face_boxes = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(24, 24))
        for x, y, fw, fh in face_boxes:
            cv2.ellipse(faces, (x + fw // 2, y + fh // 2), (int(fw * 0.65), int(fh * 0.7)), 0, 0, 360, 255, -1)
        if len(face_boxes):
            subject |= faces > 0
        notes.append(f"Ưu tiên {len(face_boxes)} khuôn mặt chính diện được nhận diện.")
    check()
    return Regions(subject, text > 0, faces > 0, boxes, notes)


def smooth_path(points, strength):
    points = np.asarray(points, np.float32)
    if len(points) < 4:
        return points
    # Two Chaikin passes remove polygon corners without fitting wild splines.
    for _ in range(2):
        a = points[:-1] * 0.75 + points[1:] * 0.25
        b = points[:-1] * 0.25 + points[1:] * 0.75
        refined = np.empty((len(a) * 2, 2), np.float32)
        refined[0::2], refined[1::2] = a, b
        points = np.vstack((points[0], refined, points[-1]))
    distance = np.r_[0, np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
    if distance[-1] < 1:
        return points[:1]
    positions = np.linspace(0, distance[-1], max(2, int(distance[-1] / (1.2 + strength))))
    return np.column_stack((np.interp(positions, distance, points[:, 0]),
                            np.interp(positions, distance, points[:, 1]))).astype(np.float32)


@dataclass
class Stroke:
    points: np.ndarray
    region: str
    kind: str
    darkness: float
    face: bool = False

    def prepare(self, scale_x, scale_y):
        self.points = self.points * np.array([scale_x, scale_y], np.float32)
        self.distances = np.r_[0, np.cumsum(np.linalg.norm(np.diff(self.points, axis=0), axis=1))]
        self.length = float(self.distances[-1])
        return self


def split_regions(points, labels):
    if len(points) < 2:
        return
    h, w = labels.shape
    rounded = np.rint(points).astype(np.int32)
    ids = labels[np.clip(rounded[:, 1], 0, h - 1), np.clip(rounded[:, 0], 0, w - 1)]
    boundaries = np.r_[0, np.flatnonzero(np.diff(ids)) + 1, len(points)]
    for begin, end in zip(boundaries[:-1], boundaries[1:]):
        if end - begin >= 2:
            yield points[begin:end], ("background", "subject", "text")[ids[begin]]


def trace_strokes(rgb, regions, cfg, check):
    h, w = rgb.shape[:2]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    # Bilateral smoothing keeps the large facial/object edges and rejects pixel noise.
    filtered = cv2.bilateralFilter(gray, 5, 20 + cfg.smoothness * 25, 5)
    low = int(22 + (1 - cfg.detail) * 60)
    edges = cv2.Canny(filtered, low, low * 2.5, L2gradient=True)
    edges[:2] = edges[-2:] = 0
    edges[:, :2] = edges[:, -2:] = 0
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    labels = regions.labels
    strokes = []
    min_length = max(3.0, min(h, w) * (0.012 - cfg.detail * 0.009))
    # Keep main contours first if a very detailed image reaches the path budget.
    contours = sorted(contours, key=lambda contour: cv2.arcLength(contour, False), reverse=True)
    max_contours = int(800 + cfg.detail * 2200)
    for index, contour in enumerate(contours[:max_contours]):
        if index % 50 == 0:
            check()
        if cv2.arcLength(contour, False) < min_length:
            continue
        points = cv2.approxPolyDP(contour, 0.35 + cfg.smoothness * 0.45, False).reshape(-1, 2)
        points = smooth_path(points, cfg.smoothness)
        for part, region in split_regions(points, labels):
            rounded = np.rint(part).astype(np.int32)
            x, y = np.clip(rounded[:, 0], 0, w - 1), np.clip(rounded[:, 1], 0, h - 1)
            face = bool(np.any(regions.faces[y, x]))
            # Keep skin/object contours graphite-light; detected text stays legible.
            darkness = 0.68 if region == "text" else (0.32 if face else 0.36)
            strokes.append(Stroke(part, region, "line", darkness, face))
    check()
    # Curved diagonal hatching, clipped into actual tonal and semantic regions.
    # A second, lighter crossing pass appears only in the deepest shadows.
    spacing = max(3, round(min(h, w) / (55 + cfg.detail * 65)))
    shade_gray = cv2.GaussianBlur(gray, (0, 0), 1.0)
    extent = math.hypot(w, h)
    for angle, cutoff, multiplier in ((-math.pi / 4, 245, 1), (math.pi / 5, 105, 2)):
        direction = np.array([math.cos(angle), math.sin(angle)], np.float32)
        normal = np.array([-direction[1], direction[0]], np.float32)
        for row, offset in enumerate(np.arange(-extent, extent, spacing * multiplier)):
            if row % 15 == 0:
                check()
            along = np.arange(-extent, extent, 2.0)
            wave = np.sin(along / 32 + row * 0.21) * cfg.smoothness * 1.4
            points = np.array([w / 2, h / 2]) + along[:, None] * direction + (offset + wave)[:, None] * normal
            xy = np.rint(points).astype(np.int32)
            inside = (xy[:, 0] >= 1) & (xy[:, 0] < w - 1) & (xy[:, 1] >= 1) & (xy[:, 1] < h - 1)
            valid = np.zeros(len(xy), bool)
            valid[inside] = shade_gray[xy[inside, 1], xy[inside, 0]] < cutoff
            boundaries = np.r_[0, np.flatnonzero(np.diff(valid)) + 1, len(points)]
            for begin, end in zip(boundaries[:-1], boundaries[1:]):
                if not valid[begin] or end - begin < 3:
                    continue
                for part, region in split_regions(points[begin:end].astype(np.float32), labels):
                    if len(part) < 3:
                        continue
                    rounded = np.rint(part).astype(np.int32)
                    darkness = (255 - float(shade_gray[rounded[:, 1], rounded[:, 0]].mean())) / 255
                    strokes.append(Stroke(part, region, "shade", darkness * 0.16))
    check()
    return strokes, spacing


class StrokeRenderer:
    def __init__(self, image, cfg, check, report=lambda **kw: None, regions=None):
        self.cfg, self.check = cfg, check
        self.width, self.height = image.size
        self.rgb = np.asarray(image.convert("RGB"))
        scale = min(1, 900 / max(image.size))
        planning = cv2.resize(self.rgb, (max(16, round(self.width * scale)), max(16, round(self.height * scale))),
                              interpolation=cv2.INTER_AREA)
        report(status="Phân tích chủ thể, khuôn mặt và chữ trên máy…")
        self.regions = regions or analyze_regions(planning, cfg, check)
        if self.regions.subject.shape != planning.shape[:2]:
            raise ValueError("Bản đồ vùng không cùng kích thước với ảnh lập nét.")
        check()
        report(status="Tạo nét cong, thứ tự vẽ và các lớp đánh bóng…")
        strokes, spacing = trace_strokes(planning, self.regions, cfg, check)
        self.spacing = spacing * self.width / planning.shape[1]
        self.strokes = [s.prepare(self.width / planning.shape[1], self.height / planning.shape[0]) for s in strokes]
        self.strokes = [s for s in self.strokes if s.length > 0.2]
        priority = cfg.priority.split("_") if cfg.priority != "natural" else ["subject", "background", "text"]
        rank = {region: index for index, region in enumerate(priority)}

        def sort_key(s):
            middle = s.points[len(s.points) // 2]
            if cfg.priority == "natural":
                return (s.kind == "shade", round(middle[1] / 24), middle[0])
            # Text is ordered by line, then left to right; faces precede other subject details.
            if s.region == "text":
                if self.regions.text_boxes:
                    centers = [box.mean(axis=0) * [self.width / planning.shape[1], self.height / planning.shape[0]]
                               for box in self.regions.text_boxes]
                    closest = min(centers, key=lambda center: abs(center[1] - middle[1]))
                    row = round(closest[1] / 12)
                else:
                    row = round(middle[1] / 40)
                return (rank[s.region], s.kind == "shade", row, float(s.points[:, 0].min()))
            return (rank[s.region], s.kind == "shade", not s.face, -s.length)

        self.strokes.sort(key=sort_key)
        self.starts, self.ends = [], []
        budget = 0.0
        previous = None
        for stroke in self.strokes:
            gap = min(24.0, float(np.linalg.norm(stroke.points[0] - previous)) * 0.08) if previous is not None else 0
            budget += gap
            self.starts.append(budget)
            speed = cfg.fill_speed if stroke.kind == "shade" else 1.0
            budget += stroke.length / speed
            self.ends.append(budget)
            previous = stroke.points[-1]
        self.starts, self.ends = np.asarray(self.starts), np.asarray(self.ends)
        self.total_cost = max(1.0, budget)
        seconds = cfg.duration if cfg.duration > 0 else min(180, max(6, self.total_cost / 850))
        self.draw_frames = max(2, round(seconds / cfg.pen_speed * cfg.fps))
        self.frame_count = self.draw_frames + round(cfg.hold * cfg.fps)
        self.labels = cv2.resize(self.regions.labels, (self.width, self.height), interpolation=cv2.INTER_NEAREST)
        self._prepare_paper()
        self.reset()
        report(status=f"Đã lập {len(self.strokes):,} nét · {len(self.regions.text_boxes)} vùng chữ · "
                      f"{self.draw_frames / cfg.fps:.1f}s vẽ", analysis=self.analysis_preview(), notes=self.regions.notes)

    def _prepare_paper(self):
        cfg = self.cfg
        darkness, _, grain_scale = STYLES[cfg.pencil_type]
        rng = np.random.default_rng(2026)
        grain = rng.normal(0, (cfg.texture * 18 + 0.15) * grain_scale, (self.height, self.width)).astype(np.float32)
        self.paper = np.clip(253 + grain, 0, 255)
        gray = cv2.cvtColor(self.rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
        gray = np.clip((gray - 127.5) * cfg.contrast + 127.5, 0, 255)
        blur = cv2.GaussianBlur(255 - gray, (0, 0), max(1, cfg.softness))
        dodge = np.minimum(255, gray * 255 / np.maximum(255 - blur, 1))
        tone = (dodge * 0.72 + gray * 0.28)
        if cfg.effect == "color":
            target = self.rgb.astype(np.float32) * 0.65 + tone[:, :, None] * 0.35
        else:
            target = np.repeat(tone[:, :, None], 3, axis=2)
        self.tone_delta = np.maximum(0, 255 - target) * min(1.1, darkness)
        y, x = np.indices((self.height, self.width), dtype=np.float32)
        radial = ((x / self.width - 0.5) ** 2 + (y / self.height - 0.5) ** 2) / 0.5
        self.vignette = 1 - cfg.vignette * np.clip(radial, 0, 1)
        ys, xs = np.where(self.labels == 1)
        self.focus = (float(xs.mean()) / self.width, float(ys.mean()) / self.height) if len(xs) else (0.5, 0.5)

    def reset(self):
        self.line_layer = np.full((self.height, self.width), 255, np.uint8)
        self.shade_layer = np.zeros((self.height, self.width), np.uint8)
        self.cursor = 0
        self.drawn_distance = 0.0
        self.last_budget = 0.0
        self.pen = None

    def analysis_preview(self):
        overlay = self.rgb.copy()
        for value, color in ((1, (60, 180, 100)), (2, (230, 160, 40))):
            mask = self.labels == value
            overlay[mask] = (overlay[mask].astype(np.float32) * 0.55 + np.array(color) * 0.45).astype(np.uint8)
        faces = cv2.resize(self.regions.faces.astype(np.uint8), (self.width, self.height), interpolation=cv2.INTER_NEAREST) > 0
        overlay[faces] = (overlay[faces].astype(np.float32) * 0.6 + np.array([70, 140, 250]) * 0.4).astype(np.uint8)
        result = Image.fromarray(overlay)
        result.thumbnail((640, 480), Image.Resampling.LANCZOS)
        return result

    @staticmethod
    def point_at(stroke, distance):
        return np.array([np.interp(distance, stroke.distances, stroke.points[:, dimension]) for dimension in (0, 1)], np.float32)

    def _draw(self, stroke, start, end, index):
        if end <= start:
            return
        begin = np.searchsorted(stroke.distances, start, side="right")
        stop = np.searchsorted(stroke.distances, end, side="left")
        points = np.vstack((self.point_at(stroke, start), stroke.points[begin:stop], self.point_at(stroke, end)))
        darkness, width_scale, _ = STYLES[self.cfg.pencil_type]
        base_width = self.cfg.line_width * min(self.width, self.height) / 720 * width_scale
        if stroke.region == "text":
            base_width *= 0.72
        # Stable pressure per path: rendering the same picture at a different FPS
        # must not change its finished tonal values.
        pressure = 0.86 + 0.10 * math.sin(index * 1.71)
        physical_width = base_width * pressure
        width = max(1, round(physical_width))
        color = int(np.clip(255 * (1 - stroke.darkness * darkness * pressure), 0, 254))
        if physical_width < 1:
            # Fractional coverage keeps thin strokes meaningful in small previews.
            color = round(255 - (255 - color) * physical_width)
        xy = np.rint(points).astype(np.int32)
        padding = max(width + 2, math.ceil(self.spacing * 0.9))
        x0, y0 = np.maximum(np.min(xy, axis=0) - padding, 0)
        x1, y1 = np.minimum(np.max(xy, axis=0) + padding + 1, [self.width, self.height])
        if x1 <= x0 or y1 <= y0:
            return
        region_id = {"background": 0, "subject": 1, "text": 2}[stroke.region]
        allowed = self.labels[y0:y1, x0:x1] == region_id
        local = xy - np.array([x0, y0])
        layer = np.full((y1 - y0, x1 - x0), 255, np.uint8)
        cv2.polylines(layer, [local], False, color, width, lineType=cv2.LINE_AA)
        layer[~allowed] = 255
        self.line_layer[y0:y1, x0:x1] = np.minimum(self.line_layer[y0:y1, x0:x1], layer)
        if stroke.kind == "shade":
            coverage = np.zeros(layer.shape, np.uint8)
            cv2.polylines(coverage, [local], False, 255, max(2, round(self.spacing * 1.9)), lineType=cv2.LINE_AA)
            coverage[~allowed] = 0
            self.shade_layer[y0:y1, x0:x1] = np.maximum(self.shade_layer[y0:y1, x0:x1], coverage)
        self.pen = xy[-1].astype(float)

    def _advance(self, budget):
        if budget < self.last_budget:
            self.reset()
        while self.cursor < len(self.strokes):
            if self.cursor % 50 == 0:
                self.check()
            stroke = self.strokes[self.cursor]
            if budget <= self.starts[self.cursor]:
                # Lift and glide between paths; no connecting line crosses the paper.
                previous = self.strokes[self.cursor - 1].points[-1] if self.cursor else stroke.points[0]
                start_time = self.ends[self.cursor - 1] if self.cursor else 0
                t = np.clip((budget - start_time) / max(self.starts[self.cursor] - start_time, 1e-6), 0, 1)
                t = t * t * (3 - 2 * t)
                self.pen = previous * (1 - t) + stroke.points[0] * t
                break
            speed = self.cfg.fill_speed if stroke.kind == "shade" else 1.0
            distance = min(stroke.length, (budget - self.starts[self.cursor]) * speed)
            self._draw(stroke, self.drawn_distance, distance, self.cursor)
            self.drawn_distance = distance
            if budget < self.ends[self.cursor]:
                break
            self.cursor += 1
            self.drawn_distance = 0
        self.last_budget = budget

    def frame(self, progress, scene_progress=None):
        progress = float(np.clip(progress, 0, 1))
        scene_progress = progress if scene_progress is None else float(np.clip(scene_progress, 0, 1))
        self._advance(progress * self.total_cost)
        shade = cv2.GaussianBlur(self.shade_layer, (0, 0), max(0.4, min(self.width, self.height) / 1000)).astype(np.float32) / 255
        # Prevent the soft shade from leaking from one scheduled region into another.
        shade *= self.shade_layer > 0
        pixels = self.paper[:, :, None] - self.tone_delta * shade[:, :, None]
        pixels *= (self.line_layer.astype(np.float32) / 255)[:, :, None]
        pixels *= self.vignette[:, :, None]
        frame = np.clip(pixels, 0, 255).astype(np.uint8)
        if self.cfg.show_pencil and 0 < progress < 1 and self.pen is not None:
            self._draw_pencil(frame, self.pen, scene_progress)
        if self.cfg.camera > 0:
            # Small continuous push-in, focused on the detected subject; no random shake.
            t = scene_progress * scene_progress * (3 - 2 * scene_progress)
            zoom = 1 + self.cfg.camera * t
            center = (self.width * self.focus[0], self.height * self.focus[1])
            matrix = cv2.getRotationMatrix2D(center, 0, zoom)
            frame = cv2.warpAffine(frame, matrix, (self.width, self.height), flags=cv2.INTER_LINEAR,
                                   borderMode=cv2.BORDER_REFLECT_101)
        return Image.fromarray(frame)

    def _draw_pencil(self, frame, position, time_fraction):
        size = self.cfg.pen_size * min(self.width, self.height) / 720
        angle = -math.pi / 3 + math.sin(time_fraction * 7) * 0.05 * self.cfg.smoothness
        direction = np.array([math.cos(angle), math.sin(angle)])
        normal = np.array([-direction[1], direction[0]])
        tip = np.asarray(position, np.float64)
        base = tip + direction * size * 0.22
        end = tip + direction * size
        radius = size * 0.055
        body = np.rint([base + normal * radius, end + normal * radius, end - normal * radius,
                         base - normal * radius]).astype(np.int32)
        wood = np.rint([tip, base + normal * radius, base - normal * radius]).astype(np.int32)
        # RGB palette; same pen family selected by the user controls its appearance.
        palette = {"2h": (124, 158, 180), "hb": (213, 170, 65), "2b": (65, 102, 76),
                   "6b": (60, 70, 88), "charcoal": (55, 52, 49)}
        cv2.fillConvexPoly(frame, body + (2, 3), (190, 186, 180), cv2.LINE_AA)
        cv2.fillConvexPoly(frame, body, palette[self.cfg.pencil_type], cv2.LINE_AA)
        cv2.fillConvexPoly(frame, wood, (212, 177, 139), cv2.LINE_AA)
        cv2.line(frame, tuple(np.rint(tip).astype(int)), tuple(np.rint(tip + direction * size * 0.06).astype(int)),
                 (45, 43, 41), max(1, round(radius * 0.6)), cv2.LINE_AA)
