from dataclasses import replace
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from drawing_engine import LocalModels, Regions, StrokeRenderer, analyze_regions
from model_assets import model_path, verify_model
from pencil_video_studio import RenderConfig


class StrokeTests(unittest.TestCase):
    def setUp(self):
        self.cfg = RenderConfig(width=320, height=240, fps=12, duration=2, hold=0,
                                show_pencil=False, subject_detection="none", detect_text=False,
                                face_priority=False, camera=0, vignette=0)
        self.image = Image.new("RGB", (320, 240), "white")
        d = ImageDraw.Draw(self.image)
        d.ellipse((15, 40, 100, 185), fill="#536380", outline="#303030", width=2)
        d.rectangle((125, 50, 200, 180), fill="#ba7040", outline="#303030", width=2)
        d.text((217, 100), "TEXT", font=ImageFont.load_default(size=28), fill="black")
        subject = np.zeros((240, 320), bool)
        subject[:, :110] = True
        text = np.zeros_like(subject)
        text[:, 210:] = True
        self.regions = Regions(subject, text, np.zeros_like(subject), [], [])

    def renderer(self, **kwargs):
        return StrokeRenderer(self.image, replace(self.cfg, **kwargs), lambda: None, regions=self.regions)

    def test_each_priority_orders_actual_strokes(self):
        for priority in ("subject_background_text", "subject_text_background", "text_subject_background",
                         "background_subject_text"):
            renderer = self.renderer(priority=priority)
            rank = {name: i for i, name in enumerate(priority.split("_"))}
            values = [rank[s.region] for s in renderer.strokes]
            self.assertEqual(values, sorted(values))
            self.assertEqual(set(values), {0, 1, 2})

    def test_text_and_background_do_not_appear_during_subject_phase(self):
        renderer = self.renderer()
        before = np.asarray(renderer.frame(0))
        subject_last = max(i for i, s in enumerate(renderer.strokes) if s.region == "subject")
        progress = renderer.ends[subject_last] / renderer.total_cost
        during = np.asarray(renderer.frame(progress))
        np.testing.assert_array_equal(before[~self.regions.subject], during[~self.regions.subject])
        self.assertLess(during[self.regions.subject].mean(), before[self.regions.subject].mean() - 5)
        final = np.asarray(renderer.frame(1))
        self.assertLess(final[self.regions.text].mean(), before[self.regions.text].mean() - 2)

    def test_brush_controls_change_result_and_timing(self):
        thin = np.asarray(self.renderer(line_width=0.5).frame(1)).astype(float)
        thick = np.asarray(self.renderer(line_width=5).frame(1)).astype(float)
        self.assertLess(thick.mean(), thin.mean())
        hard = np.asarray(self.renderer(pencil_type="2h").frame(1)).astype(float)
        soft = np.asarray(self.renderer(pencil_type="6b").frame(1)).astype(float)
        self.assertLess(soft.mean(), hard.mean())
        normal, fast = self.renderer(pen_speed=1), self.renderer(pen_speed=2)
        self.assertEqual(normal.draw_frames, fast.draw_frames * 2)

    def test_auto_duration_and_pencil_visibility(self):
        renderer = self.renderer(duration=0)
        self.assertGreaterEqual(renderer.draw_frames, 6 * self.cfg.fps)
        hidden = np.asarray(self.renderer(show_pencil=False).frame(0.5))
        visible = np.asarray(self.renderer(show_pencil=True).frame(0.5))
        self.assertFalse(np.array_equal(hidden, visible))

    def test_backward_seek_resets_drawing(self):
        renderer = self.renderer()
        reference = np.asarray(renderer.frame(0)).copy()
        renderer.frame(1)
        np.testing.assert_array_equal(reference, np.asarray(renderer.frame(0)))

    def test_camera_and_color_preserve_frame_dimensions(self):
        renderer = self.renderer(camera=0.06, effect="color")
        a = np.asarray(renderer.frame(1, 0))
        b = np.asarray(renderer.frame(1, 1))
        self.assertEqual(b.shape, (240, 320, 3))
        self.assertFalse(np.array_equal(a, b))
        self.assertFalse(np.array_equal(b[:, :, 0], b[:, :, 1]))

    def test_face_strokes_precede_other_subject_lines(self):
        self.regions.faces[40:110, :110] = True
        renderer = self.renderer()
        lines = [s for s in renderer.strokes if s.region == "subject" and s.kind == "line"]
        flags = [s.face for s in lines]
        self.assertTrue(any(flags))
        self.assertEqual(flags, sorted(flags, reverse=True))

    def test_cancel_checked_during_path_planning(self):
        calls = []
        def check():
            calls.append(1)
            if len(calls) > 3:
                raise InterruptedError("cancelled")
        with self.assertRaises(InterruptedError):
            StrokeRenderer(self.image, self.cfg, check, regions=self.regions)

    def test_real_text_detector_finds_text(self):
        image = Image.new("RGB", (640, 200), "white")
        draw = ImageDraw.Draw(image)
        draw.text((30, 55), "PENCIL STUDIO", font=ImageFont.load_default(size=52), fill="black")
        boxes = LocalModels.text(np.asarray(image))
        self.assertGreaterEqual(len(boxes), 1)
        points = np.vstack(boxes)
        self.assertGreater(float(points[:, 0].max()), 300)
        self.assertGreater(float(points[:, 1].max()), 80)

    @unittest.skipUnless(model_path().is_file(), "Run python model_assets.py to install subject model")
    def test_real_subject_model_mask(self):
        verify_model(model_path())
        mask = LocalModels.subject(np.asarray(self.image))
        self.assertEqual(mask.shape, (240, 320))
        self.assertTrue(np.all(np.isfinite(mask)))
        self.assertGreater(float(mask.max() - mask.min()), 0.5)

    def test_model_corruption_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "u2netp.onnx"
            fake.write_bytes(b"not a model")
            with self.assertRaises(ValueError):
                verify_model(fake)


if __name__ == "__main__":
    unittest.main()
