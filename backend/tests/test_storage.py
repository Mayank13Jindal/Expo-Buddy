import os
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core.storage import (
    MARKER,
    StorageGuard,
    StorageUnavailable,
    Volume,
    configured_volumes,
    inspect_volume,
)


def test_all_configured_volumes_are_checked(settings: Settings):
    guard = StorageGuard(configured_volumes(settings))
    guard.require_ready()
    assert len(guard.check()) == 6


def test_missing_marker_fails_without_creating_files(settings: Settings):
    marker = settings.assets_dir / MARKER
    marker.unlink()
    guard = StorageGuard(configured_volumes(settings))
    with pytest.raises(StorageUnavailable, match="Storage drive not found: originals"):
        guard.require_ready()
    assert list(settings.assets_dir.iterdir()) == []


def test_wrong_marker_cannot_be_automatically_repaired(settings: Settings):
    marker = settings.assets_dir / MARKER
    marker.write_text(str(uuid4()))
    expected = marker.read_bytes()
    assert not inspect_volume(configured_volumes(settings)[0]).ok
    assert marker.read_bytes() == expected


def test_symbolic_marker_is_rejected(settings: Settings, tmp_path: Path):
    marker = settings.assets_dir / MARKER
    target = tmp_path / "marker-copy"
    marker.rename(target)
    marker.symlink_to(target)
    assert not inspect_volume(configured_volumes(settings)[0]).ok


def test_disk_full_prevents_writes(settings: Settings):
    volume = configured_volumes(settings)[0]
    full = Volume(volume.name, volume.path, volume.expected_id, free_floor=2**63)
    status = inspect_volume(full)
    assert not status.ok
    assert status.message == "Storage is too full: originals"


def test_guard_detects_marker_loss_and_recovery(settings: Settings):
    guard = StorageGuard(configured_volumes(settings))
    guard.require_ready()
    marker = settings.assets_dir / MARKER
    contents = marker.read_bytes()
    marker.unlink()
    with pytest.raises(StorageUnavailable):
        guard.require_ready()
    marker.write_bytes(contents)
    guard.require_ready()


def test_moving_volume_does_not_change_identity(settings: Settings, tmp_path: Path):
    volume = configured_volumes(settings)[0]
    moved = tmp_path / "moved-disk"
    volume.path.rename(moved)
    assert inspect_volume(Volume(volume.name, moved, volume.expected_id)).ok


def test_unwritable_folder_fails(settings: Settings):
    with patch.object(os, "access", return_value=False):
        assert not inspect_volume(configured_volumes(settings)[0]).ok
