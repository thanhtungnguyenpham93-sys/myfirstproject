# Validation — version 3

Source validation includes actual U²-Net subject inference, actual PP-OCR text-region
detection, contour/hatching rendering, semantic order tests, MP4 encoding and decoding,
error handling and Tkinter GUI checks on Linux with Xvfb.

31 tests passed in the Linux run with a display, including model tests. The small
packaging self-test passed: one text region detected, 294 strokes planned, 8 frames
encoded and decoded at 384 × 288. An additional portrait/text image produced one
face and one text region and was inspected visually for region placement.

The Windows CI workflow independently tests the source, builds with PyInstaller,
then launches the packaged `.exe --self-test` and checks its report before publishing.
The existence of this workflow alone is not proof that a Windows build has succeeded;
check the latest workflow result or its completed GitHub Release.

Not yet established by these checks: manual usability on every Windows DPI setting,
accuracy on arbitrary user images, hundreds of full-resolution inputs, or antivirus
reputation/code signing of the executable.
