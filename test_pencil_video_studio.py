"""Unit + integration tests. Chạy: python -m unittest -v"""
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw
import pencil_video_studio as studio


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.image = self.root / "ảnh mẫu.png"
        image = Image.new("RGB", (120, 80), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((12, 10, 55, 65), fill="#204090")
        draw.ellipse((60, 10, 110, 70), fill="#c04030")
        image.save(self.image)
        self.cfg = studio.RenderConfig(width=96, height=64, fps=10, duration=0.4,
                                       hold=0.2, show_pencil=False, subject_detection="center",
                                       detect_text=False, face_priority=False, camera=0, vignette=0, transition=0)
        self.cancel = threading.Event()

    def test_reject_invalid_configuration(self):
        for values in ({"fps": 0}, {"fps": True}, {"width": 95}, {"height": 0},
                       {"duration": float("nan")}, {"hold": float("inf")},
                       {"duration": -1}, {"texture": 4}, {"order": "invalid"},
                       {"merge": "false"}, {"width": 4000}, {"effect": None}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                replace(self.cfg, **values).validate()

    def test_settings_round_trip_unicode_and_missing_files(self):
        path = self.root / "settings" / "cấu hình.json"
        studio.save_settings(path, self.cfg, [str(self.image), str(self.root / "missing.png")], str(self.root))
        cfg, files, output = studio.load_settings(path)
        self.assertEqual(cfg, self.cfg)
        self.assertEqual(files, [str(self.image)])
        self.assertEqual(output, str(self.root))
        self.assertEqual(list(path.parent.glob(".settings-*")), [])

    def test_broken_settings_report_error_and_preserve_original(self):
        path = self.root / "settings.json"
        for content in ("{broken", "[]", '{"version": 2, "files": "bad"}',
                        '{"version": 2, "render": {"fps": "24"}}'):
            path.write_text(content)
            with self.subTest(content=content), self.assertRaises(ValueError):
                studio.load_settings(path)
            self.assertEqual(path.read_text(), content)

    def test_failed_atomic_settings_write_preserves_original(self):
        path = self.root / "settings.json"
        path.write_text("original")
        with patch.object(studio.os, "replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                studio.save_settings(path, self.cfg, [], str(self.root))
        self.assertEqual(path.read_text(), "original")
        self.assertEqual(list(self.root.glob(".settings-*")), [])

    def test_transparency_and_contain(self):
        path = self.root / "transparent.png"
        Image.new("RGBA", (80, 80), (255, 0, 0, 0)).save(path)
        image = studio.load_image(path, self.cfg)
        self.assertEqual(image.size, (96, 64))
        self.assertTrue(np.all(np.asarray(image) == 255))

    def test_exif_orientation(self):
        path = self.root / "rotated.jpg"
        image = Image.new("RGB", (80, 40), "black")
        exif = Image.Exif()
        exif[274] = 6
        image.save(path, exif=exif)
        result = np.asarray(studio.load_image(path, self.cfg))
        self.assertTrue(np.all(result[5, 48] < 10))
        self.assertTrue(np.all(result[32, 10] == 255))

    def test_renderer_progress_and_determinism(self):
        for order in studio.ORDERS.values():
            for effect in studio.EFFECTS.values():
                with self.subTest(order=order, effect=effect):
                    cfg = replace(self.cfg, order=order, effect=effect)
                    renderer = studio.PencilRenderer(self.image, cfg, self.cancel)
                    first, middle, final = [np.asarray(renderer.frame(p)) for p in (0, 0.5, 1)]
                    self.assertEqual(final.shape, (64, 96, 3))
                    self.assertGreater(first.mean(), final.mean() + 5)
                    self.assertFalse(np.array_equal(first, middle))
                    self.assertTrue(np.array_equal(final, np.asarray(renderer.frame(1))))
                    other = studio.PencilRenderer(self.image, cfg, self.cancel)
                    self.assertTrue(np.array_equal(final, np.asarray(other.frame(1))))
                    if effect == "pencil":
                        self.assertTrue(np.array_equal(final[:, :, 0], final[:, :, 1]))

    def test_image_pixel_limit(self):
        with patch.object(studio.Image, "MAX_IMAGE_PIXELS", 100):
            with self.assertRaisesRegex(ValueError, "Không đọc được ảnh"):
                studio.load_image(self.image, self.cfg)

    def test_mailbox_retains_only_latest_preview(self):
        mailbox = studio.Mailbox()
        for i in range(1000):
            mailbox.report(progress=i / 1000, preview=i)
        self.assertEqual(mailbox.take()["preview"], 999)
        self.assertEqual(mailbox.take(), {})

    def test_missing_ffmpeg(self):
        import imageio_ffmpeg
        with patch.object(studio.shutil, "which", return_value=None), \
                patch.object(imageio_ffmpeg, "get_ffmpeg_exe", side_effect=RuntimeError("missing")):
            with self.assertRaisesRegex(RuntimeError, "Không tìm thấy FFmpeg"):
                studio.find_ffmpeg()

    def test_missing_input_and_pre_cancel_do_not_create_output(self):
        output = self.root / "output"
        with self.assertRaises(ValueError):
            studio.run_batch([self.root / "missing.png"], self.cfg, output, self.cancel)
        self.cancel.set()
        with self.assertRaises(studio.Cancelled):
            studio.run_batch([self.image], self.cfg, output, self.cancel)
        self.assertFalse(output.exists())

    def probe(self, path):
        result = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_streams",
                                 "-show_format", "-of", "json", str(path)], check=True, capture_output=True)
        return json.loads(result.stdout)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Cần FFmpeg và ffprobe")
    def test_real_mp4_separate_and_merged(self):
        for merge in (False, True):
            with self.subTest(merge=merge):
                cfg = replace(self.cfg, merge=merge)
                progress = []
                outputs = studio.run_batch([self.image, self.image], cfg, self.root / "output", self.cancel,
                                           lambda **kw: progress.append(kw.get("progress", 0)))
                self.assertEqual(len(outputs), 1 if merge else 2)
                for output in outputs:
                    probe = self.probe(output)
                    stream = probe["streams"][0]
                    self.assertEqual(stream["codec_name"], "h264")
                    self.assertEqual(stream["pix_fmt"], "yuv420p")
                    self.assertEqual((stream["width"], stream["height"]), (96, 64))
                    count = cfg.frame_count * (2 if merge else 1)
                    self.assertEqual(int(stream["nb_read_frames"]), count)
                    self.assertAlmostEqual(float(probe["format"]["duration"]), count / cfg.fps, places=2)
                    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", output, "-f", "rawvideo",
                                          "-pix_fmt", "rgb24", "pipe:1"], check=True, capture_output=True).stdout
                    frames = np.frombuffer(raw, np.uint8).reshape(count, 64, 96, 3)
                    self.assertGreater(frames[0].mean(), frames[cfg.draw_frames - 1].mean() + 5)
                    # H.264 là nén mất dữ liệu: đánh giá sai số toàn ảnh, không yêu cầu
                    # từng pixel ở các frame I/P/B giống hệt nhau sau giải mã.
                    reference = np.asarray(studio.PencilRenderer(self.image, cfg, self.cancel).frame(1), dtype=float)
                    for frame_index in range(cfg.draw_frames - 1, cfg.frame_count):
                        mse = np.mean((frames[frame_index].astype(float) - reference) ** 2)
                        self.assertLess(mse, 16, "Ảnh giữ cuối bị thay đổi quá mức sau mã hóa")
                self.assertEqual(progress[-1], 1)
                self.assertEqual(list((self.root / "output").rglob(".render-*")), [])

    @unittest.skipUnless(shutil.which("ffmpeg"), "Cần FFmpeg")
    def test_cancel_during_render_removes_partial_video(self):
        def report(**kwargs):
            if "progress" in kwargs:
                self.cancel.set()
        output = self.root / "output"
        with self.assertRaises(studio.Cancelled):
            studio.run_batch([self.image], replace(self.cfg, duration=10), output, self.cancel, report)
        self.assertEqual(list(output.iterdir()), [])

    @unittest.skipUnless(shutil.which("ffmpeg"), "Cần FFmpeg")
    def test_corrupt_later_image_preserves_completed_video(self):
        corrupt = self.root / "broken.png"
        corrupt.write_text("not an image")
        output = self.root / "output"
        with self.assertRaises(studio.BatchError) as result:
            studio.run_batch([self.image, corrupt], self.cfg, output, self.cancel)
        self.assertEqual(len(result.exception.outputs), 1)
        self.assertTrue(Path(result.exception.outputs[0]).is_file())
        self.assertEqual(len(list(output.rglob("*.mp4"))), 1)

    def test_writer_never_overwrites_existing_file(self):
        output = self.root / "existing.mp4"
        output.write_bytes(b"do not touch")
        with self.assertRaises(FileExistsError):
            studio.VideoWriter(output, self.cfg, "ffmpeg", self.cancel)
        self.assertEqual(output.read_bytes(), b"do not touch")

    @unittest.skipUnless(shutil.which("ffmpeg"), "Cần FFmpeg")
    def test_encoder_failure_removes_partial_video(self):
        # Python không hiểu đối số FFmpeg, nên encoder giả thoát với mã lỗi.
        import sys
        output = self.root / "failed.mp4"
        with self.assertRaises(RuntimeError):
            with studio.VideoWriter(output, self.cfg, sys.executable, self.cancel) as writer:
                writer.write(Image.new("RGB", (96, 64), "white"))
                writer.finish()
        self.assertFalse(output.exists())
        self.assertEqual(list(self.root.glob(".render-*")), [])

    def test_cli_validation_has_nonzero_exit(self):
        import sys
        result = subprocess.run([sys.executable, str(Path(studio.__file__)), "--headless", "--fps", "0",
                                 str(self.image)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("FPS", result.stderr)

    def pump_gui(self, root, app, timeout=15):
        deadline = time.monotonic() + timeout
        while app.busy() and time.monotonic() < deadline:
            root.update()
            time.sleep(0.01)
        self.assertFalse(app.busy(), "Tác vụ giao diện không kết thúc đúng hạn")

    @unittest.skipUnless(studio.tk is not None and (os.name == "nt" or os.environ.get("DISPLAY")),
                         "Cần Tkinter, màn hình X và FFmpeg")
    def test_gui_preview_export_and_duplicate_start(self):
        root = studio.tk.Tk()
        self.addCleanup(root.destroy)
        with patch.object(studio.messagebox, "showinfo") as info, patch.object(studio.messagebox, "showerror") as error:
            app = studio.App(root, self.root / "gui.json", [str(self.image)])
            app.get_cfg = lambda: self.cfg
            app.v["out"].set(str(self.root / "gui-output"))
            root.update()
            app.show_preview()
            self.pump_gui(root, app)
            self.assertIsNotNone(app.photo)
            app.start()
            original_worker = app.worker
            app.start()
            self.assertIs(app.worker, original_worker)
            self.pump_gui(root, app)
            self.assertEqual(len(app.outputs), 1)
            self.assertTrue(Path(app.outputs[0]).is_file())
            self.assertEqual(str(app.btn_start["state"]), "normal")
            self.assertEqual(str(app.btn_stop["state"]), "disabled")
            error.assert_not_called()
            info.assert_called_once()

    @unittest.skipUnless(studio.tk is not None and (os.name == "nt" or os.environ.get("DISPLAY")),
                         "Cần Tkinter, màn hình X và FFmpeg")
    def test_gui_cancel_restores_controls(self):
        root = studio.tk.Tk()
        self.addCleanup(root.destroy)
        with patch.object(studio.messagebox, "showerror") as error:
            app = studio.App(root, self.root / "gui.json", [str(self.image)])
            app.get_cfg = lambda: replace(self.cfg, duration=30)
            app.v["out"].set(str(self.root / "gui-output"))
            app.start()
            app.stop()
            self.pump_gui(root, app)
            self.assertIn("Đã dừng", app.status["text"])
            self.assertEqual(str(app.btn_start["state"]), "normal")
            self.assertEqual(app.outputs, [])
            error.assert_not_called()

    @unittest.skipUnless(studio.tk is not None and (os.name == "nt" or os.environ.get("DISPLAY")), "Cần Tkinter và màn hình X")
    def test_gui_actions_visible_at_minimum_window_size(self):
        root = studio.tk.Tk()
        self.addCleanup(root.destroy)
        app = studio.App(root, self.root / "gui.json")
        for size in ("1120x820", "900x700"):
            root.geometry(size)
            app.tabs.select(1)
            root.update()
            for widget in (app.btn_start, app.btn_stop, app.status, app.btn_open):
                with self.subTest(size=size, widget=widget):
                    self.assertTrue(widget.winfo_ismapped())
                    self.assertGreater(widget.winfo_width(), 10)
                    self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(),
                                         root.winfo_rooty() + root.winfo_height())

    @unittest.skipUnless(studio.tk is not None and (os.name == "nt" or os.environ.get("DISPLAY")), "Cần màn hình")
    def test_hand_controls_reach_render_configuration(self):
        root = studio.tk.Tk()
        self.addCleanup(root.destroy)
        app = studio.App(root, self.root / "gui.json")
        root.geometry("900x700")
        app.tabs.select(1)
        app.settings_tabs.select(2)
        app.v["tool_style"].set("Tay trái cầm bút")
        app.v["skin_tone"].set("Da sẫm")
        app.v["hand_size"].set("135")
        root.update()
        cfg = app.get_cfg()
        self.assertEqual((cfg.tool_style, cfg.skin_tone, cfg.hand_size), ("left_hand", "dark", 135))
        for widget, _ in app.controls:
            variable = str(widget.cget("textvariable")) if "textvariable" in widget.keys() else ""
            if variable == str(app.v["hand_size"]):
                self.assertTrue(widget.winfo_ismapped())
                self.assertLess(widget.winfo_rooty() + widget.winfo_height(), root.winfo_rooty() + root.winfo_height())

    @unittest.skipUnless(studio.tk is not None and (os.name == "nt" or os.environ.get("DISPLAY")), "Cần màn hình")
    def test_select_hand_after_hidden_setting_exports_visible_hand(self):
        root = studio.tk.Tk()
        self.addCleanup(root.destroy)
        settings = self.root / "hand-gui.json"
        studio.save_settings(settings, self.cfg, [str(self.image)], str(self.root / "videos"))
        with patch.dict(studio.PRESETS, {"Kiểm thử": (320, 240)}), \
             patch.object(studio.messagebox, "showinfo"), patch.object(studio.messagebox, "showerror") as errors:
            app = studio.App(root, settings)
            self.assertEqual(app.v["tool_style"].get(), "Ẩn bút và bàn tay")
            self.assertFalse(app.get_cfg().show_pencil)
            app.v["preset"].set("Kiểm thử")
            app.v["duration"].set("0.8")
            app.v["hand_size"].set("135")
            videos = {}
            for label in studio.TOOL_STYLES:
                # Exercise the actual click -> configuration -> worker -> encoder path.
                app.tool_buttons[label].invoke()
                root.update()
                self.assertIn(label, app.tool_preview.cget("text"))
                cfg = app.get_cfg()
                self.assertTrue(cfg.show_pencil)
                app.start()
                self.pump_gui(root, app)
                errors.assert_not_called()
                self.assertEqual(len(app.outputs), 1)
                self.assertEqual(studio.load_settings(settings)[0].tool_style, studio.TOOL_STYLES[label])
                decoded = subprocess.run([studio.find_ffmpeg(), "-v", "error", "-i", app.outputs[0],
                                          "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
                                         capture_output=True, timeout=30, **studio.subprocess_options())
                self.assertEqual(decoded.returncode, 0)
                videos[studio.TOOL_STYLES[label]] = np.frombuffer(decoded.stdout, np.uint8).reshape(
                    cfg.frame_count, cfg.height, cfg.width, 3).astype(np.int16)
            for style in ("right_hand", "left_hand"):
                changed = np.max(np.abs(videos[style] - videos["pencil"]), axis=3) > 40
                self.assertGreater(changed[1:cfg.draw_frames - 1].sum(axis=(1, 2)).max(), 300)
            app.tool_buttons["Ẩn bút và bàn tay"].invoke()
            self.assertFalse(app.get_cfg().show_pencil)


if __name__ == "__main__":
    unittest.main()
