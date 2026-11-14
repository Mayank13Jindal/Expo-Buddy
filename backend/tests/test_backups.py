import json
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.core.storage import MARKER
from app.db.library import now
from app.db.operations import Backup
from app.domain.backups import retained, schedule
from app.worker.backup import run_backup
from tests.test_library import expo, upload


def fake_dump(path, settings):
    path.write_bytes(b"FAKE DUMP ONLY - unit fixture")


def test_incremental_backup_manifest_secret_exclusion_failure_warning(signed_in, engine, settings):
    _, saved = upload(signed_in, expo(signed_in))
    with Session(engine, expire_on_commit=False) as db:
        first = Backup()
        db.add(first)
        db.commit()
        run_backup(db, first, settings, dumper=fake_dump, pause=lambda settings: nullcontext())
        manifest = json.loads((settings.backup_dir / first.path / "manifest.json").read_text())
        assert len(manifest["assets"]) == 1
        assert manifest["assets"][0]["sha256"] == saved["asset"]["sha256"]
        assert (
            "encrypted_secret"
            not in (settings.backup_dir / first.path / "providers-without-secrets.json").read_text()
        )
        original_backup_inode = (
            (settings.backup_dir / first.path / "assets" / manifest["assets"][0]["path"])
            .stat()
            .st_ino
        )
        second = Backup()
        db.add(second)
        db.commit()
        run_backup(db, second, settings, dumper=fake_dump, pause=lambda settings: nullcontext())
        two = settings.backup_dir / second.path / "assets" / manifest["assets"][0]["path"]
        assert original_backup_inode == two.stat().st_ino
        (settings.backup_dir / MARKER).unlink()
        failed = Backup()
        db.add(failed)
        db.commit()
        import pytest

        with pytest.raises(RuntimeError):
            run_backup(db, failed, settings, dumper=fake_dump, pause=lambda settings: nullcontext())
        assert second.state == "complete" and two.is_file()
    status = signed_in.get("/api/v1/system/status").json()
    assert status["backup"]["warning"] and status["backup"]["state"] == "failed"


def test_nightly_schedule_retention_and_settings(signed_in, engine, settings):
    with Session(engine) as db:
        assert (
            schedule(db, settings, datetime(2026, 10, 28, 10, tzinfo=UTC)) is not None
        )  # current timezone is after default 02:00 in this fixture
        db.commit()
        assert schedule(db, settings, datetime(2026, 10, 28, 11, tzinfo=UTC)) is None
    rows = [SimpleNamespace(id=i, finished_at=now() - timedelta(days=i)) for i in range(50)]
    keep = retained(rows)
    assert set(range(7)) <= keep
    assert 7 <= len(keep) <= 11
    assert (
        signed_in.put(
            "/api/v1/system/backup-settings",
            json={"enabled": False, "hour": 1, "minute": 30, "daily_keep": 7, "weekly_keep": 4},
        ).status_code
        == 200
    )
    with Session(engine) as db:
        assert schedule(db, settings, datetime(2026, 10, 28, 11, tzinfo=UTC)) is None


def test_retention_failure_keeps_the_new_snapshot(signed_in, engine, settings, monkeypatch):
    import app.worker.backup as backup

    upload(signed_in, expo(signed_in))

    def broken_prune(db, settings):
        raise PermissionError("An old snapshot cannot be removed.")

    monkeypatch.setattr(backup, "prune", broken_prune)
    with Session(engine, expire_on_commit=False) as db:
        row = Backup()
        db.add(row)
        db.commit()
        row = run_backup(db, row, settings, dumper=fake_dump, pause=lambda settings: nullcontext())
        assert row.state == "complete"
        assert (settings.backup_dir / row.path / "manifest.json").is_file()
