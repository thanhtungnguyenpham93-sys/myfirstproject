# Pencil Video Studio 3.2.1 — Windows 10/11 x64

Download **PencilVideoStudio-Windows-x64.zip**, extract the entire archive into a new
folder, and open **PencilVideoStudio/PencilVideoStudio.exe**. Keep `_internal`.
No Python or separate FFmpeg installation is required.

This release fixes the oversized hand hiding the pencil. It replaces the cartoon
fist with a smaller, realistic-looking generated hand sprite in a relaxed writing grip.
The wrist fades softly at its edge. A separate shaded pencil is composited through
the fingers, with visible shaft before and after the grip and a sharp graphite tip.
Near image edges, the tool rotates toward the page interior around the fixed nib,
keeping the pencil from disappearing beyond the top edge.
Hand size now sets a minimum proportional pencil length: even 200% hand with a 20px
pencil preference keeps the pencil visible. Line thickness is still independent.

Choose **Thiết lập vẽ → Bàn tay → Tay phải cầm bút / Tay trái cầm bút**.
Size remains adjustable from 50–200%; all three skin tones and five pencil types work.
The asset is bundled for offline use. The hand is a generated image, not filmed footage.
Use **Vẽ thử 6s** to preview motion; **Xem tranh** is the completed picture without tools.

**Hand-preview.png** contains decoded frames from the packaged EXE's drawing videos.
**Hand-sizes.png** compares both hands at 50%, 100%, 200% with pencil preference 20.
The Windows build tests source and the packaged executable, including visible pencil
pixels on both sides of the grip in actual MP4s, before publishing this release.

Existing local AI subject/text detection, stroke ordering, pencil controls, batch/merged
MP4 exports and YouTube/TikTok/Facebook presets remain available. Detection can be
imperfect; use the region preview. The portable executable is not code-signed.
