from dataclasses import replace
import json
import tempfile
from pathlib import Path
import unittest

import numpy as np

from drawing_tools import draw_writing_tool
from pencil_video_studio import RenderConfig, save_settings, load_settings
import test_drawing_engine as fixtures


class HandTests(unittest.TestCase):
    def setUp(self):
        self.cfg = RenderConfig(tool_style="right_hand", hand_size=100, camera=0)

    def draw(self, **changes):
        canvas = np.full((601, 601, 3), 255, np.uint8)
        draw_writing_tool(canvas, (300, 230), 0.4, replace(self.cfg, **changes))
        return canvas

    def test_hand_size_changes_area_but_nib_stays_at_contact_point(self):
        areas = []
        for size in (50, 100, 200):
            picture = self.draw(hand_size=size)
            areas.append(np.any(picture < 245, axis=2).sum())
            # The graphite nib remains at the supplied drawing coordinate.
            self.assertLess(picture[228:233, 298:303].min(axis=2).min(), 80)
        self.assertGreater(areas[1], areas[0] * 1.5)
        self.assertGreater(areas[2], areas[1] * 1.5)

    def test_left_and_right_are_mirrored_around_nib(self):
        right = self.draw(tool_style="right_hand")
        left = self.draw(tool_style="left_hand")
        # The soft drop shadow retains the lighting direction; compare filled interiors.
        right_pixels = np.any(right[:, ::-1] < 180, axis=2)
        left_pixels = np.any(left < 180, axis=2)
        overlap = np.count_nonzero(right_pixels & left_pixels) / np.count_nonzero(right_pixels | left_pixels)
        self.assertGreater(overlap, 0.94)

    def test_skin_palette_changes_hand_not_pencil_tip(self):
        light, dark = self.draw(skin_tone="light"), self.draw(skin_tone="dark")
        self.assertGreater(np.count_nonzero(np.any(light != dark, axis=2)), 500)
        # Only the actual contact pixel is invariant; surrounding hand pixels differ.
        np.testing.assert_array_equal(light[230, 300], dark[230, 300])
        self.assertLess(int(light[230, 300].max()), 80)

    def test_hidden_hand_changes_no_pixels(self):
        for style in ("pencil", "left_hand", "right_hand"):
            self.assertTrue(np.all(self.draw(show_pencil=False, tool_style=style) == 255))

    def test_hands_at_edges_are_safely_clipped(self):
        for tip in ((0, 0), (63, 0), (0, 47), (63, 47), (-500, -500), (500, 500)):
            for style in ("pencil", "left_hand", "right_hand"):
                canvas = np.full((48, 64, 3), 255, np.uint8)
                draw_writing_tool(canvas, tip, 0.4, replace(self.cfg, tool_style=style, hand_size=200))
                self.assertEqual(canvas.shape, (48, 64, 3))

    def test_settings_roundtrip_and_old_version_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            expected = replace(self.cfg, tool_style="left_hand", hand_size=145, skin_tone="dark")
            save_settings(path, expected, [], directory)
            self.assertEqual(load_settings(path)[0], expected)
            path.write_text(json.dumps({"version": 3, "render": {"pen_size": 80}, "files": []}))
            loaded = load_settings(path)[0]
            self.assertEqual(loaded.tool_style, "pencil")
            self.assertEqual(loaded.hand_size, 100)
            self.assertEqual(loaded.pen_size, 80)

    def test_invalid_hand_options_rejected(self):
        for values in ({"hand_size": 0}, {"hand_size": 201}, {"hand_size": float("nan")},
                       {"tool_style": "unknown"}, {"skin_tone": "unknown"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                replace(self.cfg, **values).validate()

    def test_final_artwork_unchanged_and_hand_visible_only_while_drawing(self):
        fixture = fixtures.StrokeTests()
        fixture.setUp()
        for style in ("right_hand", "left_hand"):
            renderer = fixture.renderer(tool_style=style, show_pencil=True, hand_size=160)
            plain = fixture.renderer(show_pencil=False)
            np.testing.assert_array_equal(np.asarray(renderer.frame(0)), np.asarray(plain.frame(0)))
            self.assertFalse(np.array_equal(np.asarray(renderer.frame(0.5)), np.asarray(plain.frame(0.5))))
            # Match the same incremental progression for both reference and hand mode.
            np.testing.assert_array_equal(np.asarray(renderer.frame(1)), np.asarray(plain.frame(1)))


if __name__ == "__main__":
    unittest.main()
