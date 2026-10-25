"""Download the small U²-Net model once, with the upstream checksum enforced."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys
import tempfile
import urllib.request

MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx"
# Published by rembg/sessions/u2netp.py; never skip model verification.
MODEL_MD5 = "8e83ca70e441ab06c318d82300c84806"


def model_path():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "models" / "u2netp.onnx"


def verify_model(path):
    digest = hashlib.md5(usedforsecurity=False)
    with Path(path).open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != MODEL_MD5:
        raise ValueError("Mô hình U²-Net không đúng checksum. Chạy lại python model_assets.py.")
    return Path(path)


def install_model():
    destination = model_path()
    if destination.is_file():
        return verify_model(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".download", delete=False) as out:
            temporary = Path(out.name)
            with urllib.request.urlopen(MODEL_URL, timeout=90) as response:
                total = 0
                while chunk := response.read(256 * 1024):
                    total += len(chunk)
                    if total > 10_000_000:
                        raise ValueError("Tệp mô hình lớn bất thường; dừng tải.")
                    out.write(chunk)
        verify_model(temporary)
        os.replace(temporary, destination)
        return destination
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    print(install_model())
