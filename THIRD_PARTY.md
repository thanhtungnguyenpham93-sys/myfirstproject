# Third-party components

The application runs inference locally and launches FFmpeg as a separate process.
The Windows package includes these runtime components and model data; their own
license terms and copyright notices continue to apply.

- Python / Tkinter / Tcl/Tk: https://www.python.org/psf/license/ and https://www.tcl.tk/software/tcltk/license.html
- NumPy: https://github.com/numpy/numpy (BSD).
- Pillow: https://github.com/python-pillow/Pillow (HPND).
- OpenCV and frontal-face cascade data: https://github.com/opencv/opencv (Apache 2.0 and notices in the distributed data).
- ONNX Runtime: https://github.com/microsoft/onnxruntime (MIT).
- RapidOCR: https://github.com/RapidAI/RapidOCR (Apache 2.0).
- PP-OCRv4 detector model included by rapidocr_onnxruntime: https://github.com/PaddlePaddle/PaddleOCR (Apache 2.0).
- U²-Net model/project: https://github.com/xuebinqin/U-2-Net (Apache 2.0).
- U²-Net small ONNX distribution: https://github.com/danielgatis/rembg/releases/tag/v0.0.0 . The downloader verifies the MD5 published by rembg; it does not bypass checksum or TLS checks.
- imageio-ffmpeg wrapper and bundled executable: https://github.com/imageio/imageio-ffmpeg (wrapper BSD; the FFmpeg binary has its own license).
- FFmpeg: https://ffmpeg.org/legal.html and https://ffmpeg.org/download.html . Included builds with libx264 are GPL-enabled; consult the binary's `-L` and `-buildconf` output, upstream source and build information before redistribution. FFmpeg is a separate executable, not linked into the Python program.
- PyInstaller bootloader: https://pyinstaller.org/en/stable/license.html (GPL with distribution exception).

No third-party photo, font, song or personal image is included in the application package.

The bundled `assets/writing_hand.png` is an AI-generated transparent hand asset
created for this application. It is not a stock photograph or an image of a user.
The procedural pencil and skin-tone compositing are implemented in drawing_tools.py.
