#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path
from uuid import UUID

from storage_config import LABELS, MARKER, NAMES, read_env


def check(config: dict[str, str]) -> list[dict]:
    if os.geteuid() != int(config["APP_UID"]):
        raise ValueError("Run storage checks as APP_UID (for example: sudo -u '#1000' make check-storage)")
    results = []
    for name in NAMES:
        path = Path(config[f"{name}_DIR"])
        result = {"name": LABELS[name], "ok": False}
        try:
            marker = path / MARKER
            if not path.is_absolute() or not path.is_dir() or path.is_symlink():
                raise ValueError("Storage folder not found")
            if not marker.is_file() or marker.is_symlink():
                raise ValueError("Storage drive not found (missing marker)")
            if str(UUID(marker.read_text().strip())) != config[f"{name}_VOLUME_ID"]:
                raise ValueError("Storage drive not found (wrong marker)")
            if mount := config.get(f"{name}_MOUNT"):
                mount_path = Path(mount).resolve()
                if not os.path.ismount(mount_path):
                    raise ValueError("Expected disk is not mounted")
                if not path.resolve().is_relative_to(mount_path):
                    raise ValueError("Storage folder is outside its configured mount")
                if path.stat().st_dev != mount_path.stat().st_dev:
                    raise ValueError("Storage folder is on the wrong filesystem")
            if not os.access(path, os.W_OK, effective_ids=True):
                raise ValueError("Storage folder is not writable by APP_UID")
            disk = os.statvfs(path)
            free = disk.f_bavail * disk.f_frsize
            if name == "ASSETS" and free < int(config.get("ASSETS_FREE_FLOOR_BYTES", 5 * 1024**3)):
                raise ValueError("Not enough free space for originals")
            result.update(ok=True, free_bytes=free, device=path.stat().st_dev, message="Available")
        except (OSError, ValueError) as error:
            result["message"] = str(error)
        results.append(result)
    good = {name: result for name, result in zip(NAMES, results, strict=True) if result["ok"]}
    if "ASSETS" in good and "BACKUP" in good and good["ASSETS"]["device"] == good["BACKUP"]["device"]:
        if config.get("ALLOW_SHARED_BACKUP_DISK", "false").lower() != "true":
            good["BACKUP"].update(ok=False, message="Backups must be on a different disk")
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", type=Path, default=Path(__file__).resolve().parents[1] / ".env")
    args = parser.parse_args()
    try:
        results = check(read_env(args.env))
        print(json.dumps({"storage": results}, indent=2))
        return 0 if all(result["ok"] for result in results) else 1
    except (OSError, ValueError, KeyError) as error:
        print(f"Storage check failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

