# Validation — version 3.2.1

Source validation includes actual U²-Net subject inference, actual PP-OCR text-region
detection, contour/hatching rendering, semantic order tests, MP4 encoding and decoding,
error handling and Tkinter GUI checks on Linux with Xvfb.

44 tests passed in the Linux run with a display, including model tests and new hand
tests: nib anchoring during resizing, mirrored left/right poses, three skin palettes,
edge clipping, hidden overlays, unchanged final artwork, config migration and GUI controls.
New regression tests inspect actual shaft pixels before/after the fingers for both
hands, sizes 50/100/200, pen preferences 20/95/200 and all five pencil types.
Skin tones and exact nib contact are also checked with the largest hand/smallest pen.
A border regression checks visible shaft pixels and unchanged nib contact at all
four corners and four edge midpoints, for both hands at 200% with pen preference 20.
The packaging self-test encodes and decodes three videos (pencil, right hand, left hand),
8 frames each at 384 × 288, with real subject and text detection.
It compares decoded hand frames with pencil-only frames and requires visible differences
beyond compression noise; this catches a hand selection silently rendering as pencil-only.
A GUI test starts from saved hidden overlays, clicks each tool option, exports MP4s,
then checks the decoded videos for both hands. Hand-preview.png is a side-by-side
sample decoded from the three test videos.
The packaged self-test additionally encodes a 12-frame 720×720 MP4 and performs
24 shaft visibility checks on decoded frames across both hands, all three sizes and
two wrist poses. Hand-sizes.png is decoded from this MP4. The bundled generated
PNG sprite is loaded by this test, so missing assets cause the build to fail.
An additional portrait/text image produced one
face and one text region and was inspected visually for region placement.

The Windows CI workflow independently tests the source, builds with PyInstaller,
then launches the packaged `.exe --self-test` and checks its report before publishing.
The existence of this workflow alone is not proof that a Windows build has succeeded;
check the latest workflow result or its completed GitHub Release.

Not yet established by these checks: manual usability on every Windows DPI setting,
accuracy on arbitrary user images, hundreds of full-resolution inputs, or antivirus
reputation/code signing of the executable.
