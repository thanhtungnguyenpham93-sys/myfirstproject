# Pencil Video Studio 3.1.1 — Windows 10/11 x64

Download **PencilVideoStudio-Windows-x64.zip**, extract the entire archive, then
open **PencilVideoStudio/PencilVideoStudio.exe**. Keep its `_internal` folder.
No Python or separate FFmpeg installation is required for the portable package.

Fixed in 3.1.1: replaced the ambiguous “show pencil / hand” checkbox with four
explicit choices: pencil only, right hand, left hand, or hidden. Selecting a hand
always enables it. A live tool swatch shows the selected style and size immediately.
A new GUI-to-MP4 test checks that both hands survive export. The packaged EXE
self-test now checks visible hand pixels in decoded MP4s, not just successful encoding.
**Hand-preview.png** shows actual frames decoded from the packaged EXE test videos.

Available since 3.1: select **pencil only**, an illustrated **right hand**, or an illustrated
**left hand** holding the pencil. Adjust hand size from **50% to 200%** independently
of pencil size and line thickness, and choose among three skin tones.
Open **Thiết lập vẽ → Bàn tay**; use **Vẽ thử 6s** to preview the moving hand.
The hand follows the drawing tip and disappears when the picture is complete.

This version traces smooth image contours and curved hatching, runs local subject
segmentation and text-region detection, supports subject/background/text ordering,
2H/HB/2B/6B/charcoal pens, independent pen and line sizes, drawing/shading speeds,
preview animation, slow camera movement, merged-image transitions and social video presets.

The Windows build checks the source and the packaged executable before publication.
Subject/text detection is automatic and can be imperfect; use the region preview
to check it. This is a drawing animation, not character animation. See the included
README for controls and limitations. The portable executable is not code-signed.
