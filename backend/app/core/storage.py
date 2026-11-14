"""Read-only checks. Never create a missing directory or repair a missing marker."""

import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from app.core.config import Settings

MARKER = ".expo-buddy-volume"


@dataclass(frozen=True)
class Volume:
    name: str
    path: Path
    expected_id: UUID
    writable: bool = True
    free_floor: int = 0


@dataclass(frozen=True)
class VolumeStatus:
    name: str
    ok: bool
    message: str
    free_bytes: int | None = None
    total_bytes: int | None = None
    device: int | None = None
    warning: bool = False


def configured_volumes(settings: Settings) -> list[Volume]:
    return [
        Volume(
            "originals",
            settings.assets_dir,
            settings.assets_volume_id,
            free_floor=settings.assets_free_floor_bytes,
        ),
        Volume("previews", settings.previews_dir, settings.previews_volume_id),
        Volume("database", settings.db_dir, settings.db_volume_id, writable=False),
        Volume("models", settings.models_dir, settings.models_volume_id),
        Volume("exports", settings.exports_dir, settings.exports_volume_id),
        Volume("backups", settings.backup_dir, settings.backup_volume_id),
    ]


def inspect_volume(volume: Volume) -> VolumeStatus:
    try:
        if not volume.path.is_dir():
            raise OSError("Missing directory")
        descriptor = os.open(volume.path / MARKER, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise OSError("Invalid marker")
            marker = stream.read(128).strip()
        if marker != str(volume.expected_id):
            raise OSError("Wrong marker")
    except (OSError, UnicodeError):
        return VolumeStatus(volume.name, False, f"Storage drive not found: {volume.name}")

    try:
        if volume.writable and not os.access(volume.path, os.W_OK, effective_ids=True):
            return VolumeStatus(volume.name, False, f"Storage is not writable: {volume.name}")
        disk = os.statvfs(volume.path)
        free = disk.f_bavail * disk.f_frsize
        total = disk.f_blocks * disk.f_frsize
        if free < volume.free_floor:
            return VolumeStatus(
                volume.name,
                False,
                f"Storage is too full: {volume.name}",
                free,
                total,
                volume.path.stat().st_dev,
                True,
            )
        warning = bool(total and (total - free) / total >= 0.85)
        return VolumeStatus(
            volume.name,
            True,
            f"Storage is almost full: {volume.name}" if warning else "Available",
            free,
            total,
            volume.path.stat().st_dev,
            warning,
        )
    except OSError:
        return VolumeStatus(volume.name, False, f"Storage is unavailable: {volume.name}")


class StorageUnavailable(RuntimeError):
    pass


class StorageGuard:
    def __init__(self, volumes: list[Volume], interval: float = 30) -> None:
        self.volumes = volumes
        self.interval = interval
        self.statuses: list[VolumeStatus] = []
        self.checked_at = 0.0

    def check(self, *, force: bool = False) -> list[VolumeStatus]:
        if force or time.monotonic() - self.checked_at >= self.interval:
            self.statuses = [inspect_volume(volume) for volume in self.volumes]
            self.checked_at = time.monotonic()
        return self.statuses

    def require_ready(self) -> None:
        failures = [status.message for status in self.check(force=True) if not status.ok]
        if failures:
            raise StorageUnavailable("; ".join(failures))
