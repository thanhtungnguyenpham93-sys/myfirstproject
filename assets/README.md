# Writing hand asset

`writing_hand.png` is an AI-generated transparent RGBA hand sprite created for
this application. It contains the hand only; no user image or stock photo is used.
The pencil is drawn separately by `drawing_tools.py`, behind the pinching fingers.

Original size: 1254 × 1254. Pinch anchor: (240, 395). The source is kept intact;
the renderer applies skin tone, premultiplied-alpha filtering, wrist-edge fade,
left/right mirroring and scaling at runtime. The hand angle is fixed; only its
position follows the drawing, without wrist rotations.

The PyInstaller spec bundles this file under `_internal/assets/` so no network
request is needed when rendering. Keep the complete application folder together.
