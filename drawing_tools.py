"""Composited writing tools with a fixed nib and a proportionate, visible pencil.

The transparent hand sprite is bundled locally. A procedural pencil sits behind
its fingers; the contact point, exposed shaft and sharpened tip remain visible.
"""
from __future__ import annotations

from functools import lru_cache
import math
from pathlib import Path
import sys
import cv2
import numpy as np

TOOL_STYLES = {"Chỉ hiện bút chì": "pencil", "Tay phải cầm bút": "right_hand", "Tay trái cầm bút": "left_hand"}
SKIN_TONES = {"Da sáng": "light", "Da trung bình": "medium", "Da sẫm": "dark"}
PEN_COLORS = {"2h": (124, 158, 180), "hb": (213, 170, 65), "2b": (65, 102, 76),
              "6b": (60, 70, 88), "charcoal": (55, 52, 49)}
# Pinch between thumb and index in the original 1254-square sprite. Normalized
# coordinates allow the cached texture to be downsampled without moving the grip.
GRIP = np.array([240 / 1254, 395 / 1254], np.float32)


@lru_cache(maxsize=3)
def hand_texture(skin_tone):
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    path = root / "assets" / "writing_hand.png"
    data = np.fromfile(str(path), dtype=np.uint8) if path.is_file() else None
    rgba = cv2.imdecode(data, cv2.IMREAD_UNCHANGED) if data is not None else None
    if rgba is None or rgba.ndim != 3 or rgba.shape[2] != 4:
        raise RuntimeError("Thiếu mẫu bàn tay. Hãy giải nén toàn bộ bản ứng dụng, gồm thư mục _internal.")
    rgba = cv2.cvtColor(rgba, cv2.COLOR_BGRA2RGBA).astype(np.float32) / 255
    # Fade the far wrist into the page instead of showing the sprite's square cut.
    y, x = np.indices(rgba.shape[:2], dtype=np.float32)
    edge = np.clip(np.minimum((rgba.shape[1]-1-x) / (rgba.shape[1]*0.18),
                              (rgba.shape[0]-1-y) / (rgba.shape[0]*0.18)), 0, 1)
    rgba[:, :, 3] *= edge * edge * (3-2*edge)
    tint = {"light": (1.06, 1.06, 1.04), "medium": (0.90, 0.87, 0.83),
            "dark": (0.57, 0.46, 0.39)}[skin_tone]
    rgba[:, :, :3] = np.minimum(1, rgba[:, :, :3] * tint)
    # Premultiply before filtering so transparent edge colors cannot form halos.
    rgba[:, :, :3] *= rgba[:, :, 3:4]
    return cv2.resize(rgba, (512, 512), interpolation=cv2.INTER_AREA)


def tool_geometry(width, height, time_fraction, cfg, position=None):
    """Fixed downward nib pose, independent of path position and elapsed time.

    time_fraction and position remain accepted by existing callers; neither may
    rotate the tool. Only translation follows the stroke, including at borders.
    """
    resolution_scale = min(width, height) / 720
    hand_unit = 60 * cfg.hand_size / 100 * resolution_scale
    hand = cfg.tool_style != "pencil"
    length = cfg.pen_size * resolution_scale
    if hand:
        # A tiny independent pencil cannot be held by a large hand. pen_size is
        # a preference, with this anatomical minimum applied only in hand mode.
        length = max(length, hand_unit * 3.2)
    # direction runs from nib to the back of the pencil. Its negative y places
    # the shaft above the nib: the sharpened end always points downward.
    angle = -math.pi / 3
    direction = np.array([math.cos(angle), math.sin(angle)])
    normal = np.array([-direction[1], direction[0]])
    rotation = np.eye(2)
    if cfg.tool_style == "left_hand":
        direction[0] *= -1
        normal[0] *= -1
        rotation[0] *= -1
    # Narrow shaft independent of total length; a long pencil must not be a club.
    radius = max(1.2 * resolution_scale, min(length * 0.028, hand_unit * 0.085)) if hand else length * 0.04
    return hand_unit, length, radius, direction, normal, rotation


def draw_writing_tool(frame, position, time_fraction, cfg):
    if not cfg.show_pencil:
        return
    height, width = frame.shape[:2]
    resolution_scale = min(width, height) / 720
    unit, length, radius, direction, normal, rotation = tool_geometry(width, height, time_fraction, cfg, position)
    tip = np.asarray(position, np.float64)
    hand = cfg.tool_style != "pencil"
    grip = tip + direction * length * 0.30
    end = tip + direction * length
    bounds = [tip, end]
    transform = None
    if hand:
        texture = hand_texture(cfg.skin_tone)
        # At 100%, the entire sprite spans about 125px at 720p. This includes the
        # wrist; the fingers are much smaller than the previous cartoon fist.
        sprite_scale = unit * (1254 / 600) / texture.shape[0]
        transform = np.zeros((2, 3), np.float64)
        transform[:, :2] = rotation * sprite_scale
        transform[:, 2] = grip - transform[:, :2] @ (GRIP * texture.shape[0])
        corners = np.array([[0, 0], [512, 0], [512, 512], [0, 512]])
        bounds.extend(corners @ transform[:, :2].T + transform[:, 2])
    padding = max(5, radius * 3)
    low = np.maximum(np.floor(np.min(bounds, axis=0) - padding).astype(int), 0)
    high = np.minimum(np.ceil(np.max(bounds, axis=0) + padding).astype(int), [width, height])
    x0, y0 = low
    x1, y1 = high
    if x0 >= x1 or y0 >= y1:
        return
    canvas = frame[y0:y1, x0:x1]
    offset = np.array([x0, y0])

    def polygon(points, color):
        fixed = np.rint((points - offset) * 16).astype(np.int32)
        cv2.fillPoly(canvas, [fixed], color, lineType=cv2.LINE_AA, shift=4)

    # Small contact shadow, applied behind the pencil and hand.
    if hand:
        local = transform.copy()
        local[:, 2] -= offset
        layer = cv2.warpAffine(texture, local, (x1-x0, y1-y0), flags=cv2.INTER_LINEAR)
        shadow = cv2.GaussianBlur(layer[:, :, 3], (0, 0), max(0.5, resolution_scale * 1.5))
        canvas[:] = np.rint(canvas.astype(np.float32) * (1 - shadow[:, :, None] * 0.10)).astype(np.uint8)

    wood_length = min(length * 0.14, radius * 5)
    base = tip + direction * wood_length
    body = np.array([base + normal * radius, end + normal * radius,
                     end - normal * radius, base - normal * radius])
    color = np.array(PEN_COLORS[cfg.pencil_type])
    polygon(body, tuple(int(v) for v in color))
    polygon(np.array([base + normal * radius * 0.25, end + normal * radius * 0.25,
                      end + normal * radius, base + normal * radius]),
            tuple(int(v) for v in np.minimum(255, color * 1.15 + 15)))
    polygon(np.array([base - normal * radius * 0.45, end - normal * radius * 0.45,
                      end - normal * radius, base - normal * radius]),
            tuple(int(v) for v in color * 0.7))
    # Dark painted cap separates the exposed back of the pencil from the paper.
    cap = end - direction * radius * 2.8
    polygon(np.array([cap + normal * radius, end + normal * radius,
                      end - normal * radius, cap - normal * radius]), (48, 49, 51))
    if hand:
        alpha = layer[:, :, 3:4]
        canvas[:] = np.clip(layer[:, :, :3] * 255 + canvas.astype(np.float32) * (1-alpha), 0, 255).astype(np.uint8)
    # These stay outside the silhouette; drawing them last also guarantees an
    # unambiguous dark contact point on the exact stroke coordinate.
    polygon(np.array([tip, base + normal * radius, base - normal * radius]), (213, 174, 127))
    graphite = tip + direction * min(wood_length * 0.36, radius * 1.8)
    polygon(np.array([tip, graphite + normal * radius * 0.35,
                      graphite - normal * radius * 0.35]), (42, 40, 38))
    cv2.line(canvas, tuple(np.rint(tip-offset).astype(int)),
             tuple(np.rint(graphite-offset).astype(int)), (42, 40, 38),
             max(1, round(radius * 0.35)), cv2.LINE_AA)
