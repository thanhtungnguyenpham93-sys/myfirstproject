"""Vector writing tools. The contact point stays fixed when the hand is resized.

Hands are built-in illustrations, with no downloaded photographs or new assets.
The back of the hand is painted first, then the pencil, then gripping fingers.
"""
from __future__ import annotations

import math
import cv2
import numpy as np

TOOL_STYLES = {"Chỉ hiện bút chì": "pencil", "Tay phải cầm bút": "right_hand", "Tay trái cầm bút": "left_hand"}
SKIN_TONES = {"Da sáng": "light", "Da trung bình": "medium", "Da sẫm": "dark"}
SKINS = {
    "light": ((237, 197, 167), (249, 218, 191), (187, 137, 107), (251, 224, 206)),
    "medium": ((190, 137, 97), (215, 166, 122), (135, 86, 59), (227, 184, 153)),
    "dark": ((112, 73, 53), (142, 98, 70), (75, 47, 36), (165, 120, 96)),
}
PEN_COLORS = {"2h": (124, 158, 180), "hb": (213, 170, 65), "2b": (65, 102, 76),
              "6b": (60, 70, 88), "charcoal": (55, 52, 49)}


def curve(start, *segments):
    """Sample cubic Bézier paths in a small, normalized hand coordinate system."""
    points = [np.asarray(start, np.float64)]
    for segment in segments:
        if len(segment) == 2:
            points.append(np.asarray(segment, np.float64))
            continue
        p0 = points[-1]
        p1, p2, p3 = np.asarray(segment, np.float64).reshape(3, 2)
        for t in np.linspace(0, 1, 13)[1:]:
            points.append((1-t)**3*p0 + 3*(1-t)**2*t*p1 + 3*(1-t)*t*t*p2 + t**3*p3)
    return np.asarray(points)


PALM = curve((0.18, 0.12),
    (0.44, 0.05, 0.65, 0.29, 0.61, 0.58),
    (0.63, 0.81, 0.35, 1.03, 0.16, 1.23),
    (0.02, 1.44, -0.09, 1.68, -0.17, 1.91), (-1.05, 1.70),
    (-0.98, 1.38, -0.91, 1.08, -0.72, 0.89),
    (-0.94, 0.85, -1.01, 0.69, -0.88, 0.55),
    (-1.01, 0.45, -0.96, 0.25, -0.78, 0.21),
    (-0.76, 0.04, -0.61, -0.07, -0.43, 0.01),
    (-0.29, -0.07, -0.12, -0.02, 0.02, 0.10),
    (0.06, 0.13, 0.12, 0.14, 0.18, 0.12))
PALM_LIGHT = curve((0.17, 0.35),
    (0.43, 0.21, 0.57, 0.40, 0.43, 0.64),
    (0.26, 0.86, -0.06, 1.12, -0.19, 1.47),
    (-0.27, 1.61, -0.57, 1.53, -0.56, 1.34),
    (-0.51, 1.10, -0.35, 0.76, -0.20, 0.55),
    (-0.08, 0.39, 0.08, 0.42, 0.17, 0.35))
MIDDLE = curve((-0.10, -0.045),
    (-0.27, -0.19, -0.43, -0.10, -0.51, 0.08),
    (-0.62, 0.21, -0.78, 0.27, -0.68, 0.43),
    (-0.61, 0.57, -0.37, 0.46, -0.29, 0.34),
    (-0.12, 0.22, 0.03, 0.09, -0.10, -0.045))
INDEX = curve((0.09, -0.065),
    (0.27, -0.12, 0.40, 0.05, 0.46, 0.23),
    (0.51, 0.37, 0.44, 0.60, 0.31, 0.64),
    (0.21, 0.65, 0.19, 0.52, 0.22, 0.40),
    (0.22, 0.29, 0.19, 0.14, 0.09, 0.10),
    (-0.03, 0.06, -0.05, -0.015, 0.09, -0.065))
THUMB = curve((-0.075, -0.075),
    (-0.24, -0.13, -0.33, 0.03, -0.32, 0.15),
    (-0.36, 0.32, -0.50, 0.49, -0.42, 0.64),
    (-0.34, 0.80, -0.13, 0.77, -0.03, 0.61),
    (0.08, 0.46, 0.11, 0.26, 0.02, 0.13),
    (-0.02, 0.06, 0.035, -0.025, -0.075, -0.075))
NAIL = curve((-0.11, -0.043),
    (-0.20, -0.075, -0.27, 0.01, -0.26, 0.10),
    (-0.23, 0.15, -0.13, 0.18, -0.07, 0.12),
    (-0.04, 0.065, -0.04, -0.01, -0.11, -0.043))
CREASES = (
    curve((-0.77, 0.23), (-0.63, 0.23, -0.56, 0.34, -0.56, 0.44)),
    curve((-0.87, 0.55), (-0.75, 0.56, -0.65, 0.63, -0.64, 0.73)),
    curve((-0.73, 0.89), (-0.54, 0.88, -0.40, 1.01, -0.40, 1.15)),
    curve((-0.88, 1.49), (-0.62, 1.47, -0.36, 1.59, -0.25, 1.67)),
)


def draw_writing_tool(frame, position, time_fraction, cfg):
    """Paint RGB in place; mirroring is around the nib, never around the image."""
    if not cfg.show_pencil:
        return
    height, width = frame.shape[:2]
    resolution_scale = min(width, height) / 720
    length = cfg.pen_size * resolution_scale
    hand_unit = 90 * cfg.hand_size / 100 * resolution_scale
    angle = -math.pi / 3 + math.sin(time_fraction * 7) * 0.05 * cfg.smoothness
    direction = np.array([math.cos(angle), math.sin(angle)])
    normal = np.array([-direction[1], direction[0]])
    if cfg.tool_style == "left_hand":
        direction[0] *= -1
        normal[0] *= -1
    tip = np.asarray(position, np.float64)
    grip = tip + direction * length * 0.42
    matrix = np.stack((direction, normal), axis=0) * hand_unit

    def world(path):
        return path @ matrix + grip

    # Bounding ROI avoids copying the entire video frame to paint a hand shadow.
    hand = cfg.tool_style != "pencil"
    palm = world(PALM) if hand else np.vstack((tip, tip + direction * length))
    bounds = np.vstack((palm, tip, tip + direction * length))
    padding = max(5, length * 0.12)
    low = np.maximum(np.floor(bounds.min(axis=0) - padding).astype(int), 0)
    high = np.minimum(np.ceil(bounds.max(axis=0) + padding).astype(int), [width, height])
    x0, y0 = low
    x1, y1 = high
    if x0 >= x1 or y0 >= y1:
        return
    canvas = frame[y0:y1, x0:x1]
    offset = np.array([x0, y0])

    def polygon(points, color, outline=None):
        fixed = np.rint((points - offset) * 16).astype(np.int32)
        cv2.fillPoly(canvas, [fixed], color, lineType=cv2.LINE_AA, shift=4)
        if outline is not None:
            cv2.polylines(canvas, [fixed], True, outline, max(1, round(resolution_scale)), cv2.LINE_AA, shift=4)

    if hand:
        skin, highlight, crease, nail = SKINS[cfg.skin_tone]
        shadow = np.zeros(canvas.shape[:2], np.uint8)
        shadow_points = np.rint(palm - offset + [2 * resolution_scale, 4 * resolution_scale]).astype(np.int32)
        cv2.fillPoly(shadow, [shadow_points], 255, cv2.LINE_AA)
        shadow = cv2.GaussianBlur(shadow, (0, 0), max(0.5, resolution_scale * 2))
        canvas[:] = np.rint(canvas.astype(np.float32) * (1 - shadow[:, :, None] / 255 * 0.14)).astype(np.uint8)
        polygon(palm, skin, crease)
        polygon(world(PALM_LIGHT), highlight)
        polygon(world(MIDDLE), skin, crease)
        for path in CREASES:
            fixed = np.rint((world(path) - offset) * 16).astype(np.int32)
            cv2.polylines(canvas, [fixed], False, crease, max(1, round(resolution_scale)), cv2.LINE_AA, shift=4)

    base, end = tip + direction * length * 0.22, tip + direction * length
    radius = length * 0.055
    body = np.array([base + normal * radius, end + normal * radius, end - normal * radius, base - normal * radius])
    polygon(body, PEN_COLORS[cfg.pencil_type], (76, 67, 51))
    polygon(np.array([base + normal * radius * 0.15, end + normal * radius * 0.15,
                      end + normal * radius * 0.55, base + normal * radius * 0.55]), (236, 210, 137))
    if hand:
        # These fingers sit over the shaft, making the grip visible at all sizes.
        polygon(world(INDEX), highlight, crease)
        polygon(world(THUMB), skin, crease)
        polygon(world(NAIL), nail, crease)
    # Keep the nib in front of curled fingers, even with a large hand/small pencil.
    polygon(np.array([tip, base + normal * radius, base - normal * radius]), (222, 185, 145))
    polygon(np.array([tip, tip + direction * length * 0.075 + normal * radius * 0.3,
                      tip + direction * length * 0.075 - normal * radius * 0.3]), (42, 40, 38))
    cv2.line(canvas, tuple(np.rint(tip-offset).astype(int)),
             tuple(np.rint(tip + direction * length * 0.045 - offset).astype(int)),
             (42, 40, 38), max(1, round(radius * 0.4)), cv2.LINE_AA)
