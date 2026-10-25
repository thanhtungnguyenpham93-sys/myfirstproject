# Run on Windows using Python 3.12 x64. One folder contains all runtime dependencies.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files

datas, binaries, hiddenimports = [], [], []
for package in ('rapidocr_onnxruntime', 'onnxruntime', 'imageio_ffmpeg'):
    package_data, package_bins, package_imports = collect_all(package)
    datas += package_data
    binaries += package_bins
    hiddenimports += package_imports
datas += collect_data_files('cv2', includes=['data/*.xml'])
datas += [('models/u2netp.onnx', 'models'), ('THIRD_PARTY.md', '.')]

a = Analysis(['pencil_video_studio.py'], pathex=[], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=['pytest', 'IPython', 'matplotlib', 'pandas', 'torch'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='PencilVideoStudio',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='PencilVideoStudio')
