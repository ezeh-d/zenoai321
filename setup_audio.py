from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

from config import AUDIO_MODELS_DIR, KOKORO_MODEL_PATH, KOKORO_VOICES_PATH

FILES = {
    Path(KOKORO_MODEL_PATH): "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
    Path(KOKORO_VOICES_PATH): "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
}


def _progress(blocks: int, block_size: int, total: int) -> None:
    downloaded = min(blocks * block_size, total)
    percent = int(downloaded * 100 / total) if total else 0
    print(f"\rDownloading: {percent:3d}%", end="", flush=True)


def main() -> int:
    AUDIO_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    for destination, url in FILES.items():
        if destination.exists() and destination.stat().st_size > 1_000_000:
            print(f"Already present: {destination.name}")
            continue
        print(f"Downloading {destination.name}...")
        temp = destination.with_suffix(destination.suffix + ".part")
        try:
            urllib.request.urlretrieve(url, temp, _progress)
            print()
            temp.replace(destination)
        except Exception as error:
            temp.unlink(missing_ok=True)
            print(f"Download failed: {error}")
            return 1
    print("\nKokoro models are ready.")
    print("Run: python test_audio_engine.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
