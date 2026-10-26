# Validation — version 3.1

Source validation includes actual U²-Net subject inference, actual PP-OCR text-region
detection, contour/hatching rendering, semantic order tests, MP4 encoding and decoding,
error handling and Tkinter GUI checks on Linux with Xvfb.

40 tests passed in the Linux run with a display, including model tests and new hand
tests: nib anchoring during resizing, mirrored left/right poses, three skin palettes,
edge clipping, hidden overlays, unchanged final artwork, config migration and GUI controls.
The packaging self-test encodes and decodes three videos (pencil, right hand, left hand),
8 frames each at 384 × 288, with real subject and text detection.
An additional portrait/text image produced one
face and one text region and was inspected visually for region placement.

The Windows CI workflow independently tests the source, builds with PyInstaller,
then launches the packaged `.exe --self-test` and checks its report before publishing.
The existence of this workflow alone is not proof that a Windows build has succeeded;
check the latest workflow result or its completed GitHub Release.

Not yet established by these checks: manual usability on every Windows DPI setting,
accuracy on arbitrary user images, hundreds of full-resolution inputs, or antivirus
reputation/code signing of the executable.
