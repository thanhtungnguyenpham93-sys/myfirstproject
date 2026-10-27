# Pencil Video Studio 3.2.2 — Windows 10/11 x64

The writing hand and pencil now keep ONE fixed angle, with the nib pointing down.
Only their position follows the drawing stroke. This removes both automatic turning
near image edges and time-based wrist wobble, for right hand, left hand and pencil-only.
Selecting the other hand mirrors the fixed pose. The drawing itself does not rotate.
At page boundaries, portions outside the video frame are clipped without changing
pose or moving the nib away from the active stroke.

The natural-looking hand asset, three skin tones, 50–200% hand sizing and proportional
minimum pencil length remain available. Line thickness is independent of hand size.

Download **PencilVideoStudio-Windows-x64.zip**, extract the entire archive into a new
folder, then open **PencilVideoStudio/PencilVideoStudio.exe**. Keep `_internal`.
No Python or separate FFmpeg installation is required.
Choose **Thiết lập vẽ → Bàn tay → Tay phải cầm bút / Tay trái cầm bút** and use
**Vẽ thử 6s** to check the fixed direction before exporting a new MP4.

**Hand-preview.png** and **Hand-sizes.png** show frames decoded from the packaged
Windows EXE's test videos. Source tests verify the same pose at corners, edges,
interior positions and multiple animation times, plus unchanged rendered tool pixels
at a fixed position over time. Windows source and packaged-EXE checks run before release.
