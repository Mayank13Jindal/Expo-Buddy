#!/usr/bin/env python3
"""Explicit, revision-pinned downloads. OCR never fetches weights implicitly."""
import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

from storage_config import MARKER, read_env


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", default="ocr")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    config = read_env(root / ".env")
    destination = Path(config["MODELS_DIR"])
    marker = destination / MARKER
    if marker.is_symlink() or marker.read_text().strip() != config["MODELS_VOLUME_ID"]:
        raise SystemExit("Storage drive not found: models")
    manifest = json.loads((root / "models.lock.json").read_text())
    for model in manifest[args.kind]:
        folder = destination / model["directory"]
        folder.mkdir(parents=True, exist_ok=True)
        for filename in model["files"]:
            target = folder / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                continue
            url = f"https://huggingface.co/{model['repository']}/resolve/{model['revision']}/{filename}"
            temporary = target.with_suffix(target.suffix + ".part")
            try:
                with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as stream:
                    while chunk := response.read(1024 * 1024):
                        stream.write(chunk)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        print(f"Cached {model['repository']} at {model['revision']}")


if __name__ == "__main__":
    main()

