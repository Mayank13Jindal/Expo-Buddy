"""Consistent custom-format PostgreSQL dump and incremental immutable originals."""

import json
import logging
import os
import shutil
import subprocess
from contextlib import contextmanager

import psycopg
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.maintenance import WRITE_LOCK
from app.core.storage import StorageGuard, configured_volumes
from app.db.intelligence import ProviderSetting
from app.db.library import Asset, now
from app.db.operations import Backup
from app.db.session import build_engine
from app.domain.backups import configuration, retained
from app.domain.uploads import asset_path
from app.exports.package import digest_file


def private_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        os.chmod(path, 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2, default=str)
        stream.flush()
        os.fsync(stream.fileno())


@contextmanager
def write_pause(settings):
    with psycopg.connect(
        host=settings.database_host,
        port=settings.database_port,
        dbname=settings.database_name,
        user=settings.database_user,
        password=settings.database_password_file.read_text().strip(),
        autocommit=True,
        connect_timeout=5,
    ) as connection:
        connection.execute("SET lock_timeout = '60s'")
        connection.execute("SELECT pg_advisory_lock(%s)", (WRITE_LOCK,))
        try:
            yield
        finally:
            connection.execute("SELECT pg_advisory_unlock(%s)", (WRITE_LOCK,))


def dump_database(destination, settings):
    command = [
        "/usr/local/bin/pg_dump",
        "--host",
        settings.database_host,
        "--port",
        str(settings.database_port),
        "--username",
        settings.database_user,
        "--dbname",
        settings.database_name,
        "--format=custom",
        "--no-owner",
        "--no-acl",
        "--exclude-table-data=public.provider_settings",
        "--exclude-table-data=public.search_chunks",
        "--exclude-table-data=public.exports",
        "--file",
        str(destination),
    ]
    env = {**os.environ, "PGPASSWORD": settings.database_password_file.read_text().strip()}
    try:
        subprocess.run(  # noqa: S603 — fixed executable and argument array, no shell
            command,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=900,
        )  # noqa: S603 — fixed binary and argument array; no shell
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError(
            "The PostgreSQL backup could not finish. Check database access and backup storage."
        ) from None
    os.chmod(destination, 0o600)
    with destination.open("rb") as stream:
        os.fsync(stream.fileno())


def copy_originals(rows, destination, settings, previous=None, *, verify=True):
    manifest = []
    guard = StorageGuard(configured_volumes(settings))
    for asset in rows:
        guard.require_ready()
        source = asset_path(settings.assets_dir, asset.storage_path)
        target = asset_path(destination, asset.storage_path)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if target.is_file():
            # The pause pass skips re-hashing: this run's first pass already verified the file.
            if verify and digest_file(target) != asset.sha256:
                raise RuntimeError("A backup file checksum failed. Check the backup drive.")
        else:
            old = asset_path(previous, asset.storage_path) if previous else None
            if (
                old
                and old.is_file()
                and old.stat().st_size == asset.bytes
                and digest_file(old) == asset.sha256
            ):
                os.link(old, target)
            else:
                if not source.is_file() or source.stat().st_size != asset.bytes:
                    raise RuntimeError("An original is unavailable. Check the originals drive.")
                with source.open("rb") as incoming, target.open("xb") as output:
                    os.chmod(target, 0o600)
                    shutil.copyfileobj(incoming, output, 1024 * 1024)
                    output.flush()
                    os.fsync(output.fileno())
                if digest_file(target) != asset.sha256:
                    raise RuntimeError("An original checksum failed. Check the originals drive.")
        manifest.append(
            {
                "id": str(asset.id),
                "path": asset.storage_path,
                "sha256": asset.sha256,
                "bytes": asset.bytes,
            }
        )
    return manifest


def run_backup(db, row, settings, *, dumper=dump_database, pause=write_pause):
    db.info["backup_metadata"] = True
    if row.state == "complete":
        return row
    row.state, row.started_at, row.error = "running", now(), None
    db.commit()
    guard = StorageGuard(configured_volumes(settings))
    folder = settings.backup_dir / "snapshots" / str(row.id)
    try:
        guard.require_ready()
        previous = db.scalar(
            select(Backup)
            .where(Backup.state == "complete", Backup.id != row.id)
            .order_by(Backup.finished_at.desc())
            .limit(1)
        )
        previous_assets = (
            asset_path(settings.backup_dir, previous.path) / "assets" if previous else None
        )
        # Retry a failed backup into a new staging directory; completed snapshots are never modified.
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True, mode=0o700)
        originals = folder / "assets"
        originals.mkdir(mode=0o700)
        assets = list(db.scalars(select(Asset).where(Asset.purged_at.is_(None))))
        free = shutil.disk_usage(folder).free
        new_bytes = sum(
            asset.bytes
            for asset in assets
            if not previous_assets or not asset_path(previous_assets, asset.storage_path).is_file()
        )
        if free < new_bytes + 100 * 1024**2:
            raise RuntimeError("The backup drive needs more free space.")
        # Most bytes are copied before the short write pause. Originals are immutable.
        copy_originals(assets, originals, settings, previous_assets)
        db.commit()
        with pause(settings):
            db.expire_all()
            assets = list(db.scalars(select(Asset).where(Asset.purged_at.is_(None))))
            manifest_assets = copy_originals(
                assets, originals, settings, previous_assets, verify=False
            )
            providers = [
                {
                    column.key: getattr(provider, column.key)
                    for column in ProviderSetting.__table__.columns
                    if column.key not in ("encrypted_secret",)
                }
                | {"enabled": False}
                for provider in db.scalars(select(ProviderSetting))
            ]
            db.commit()
            dump_database_path = folder / "database.dump"
            dumper(dump_database_path, settings)
            private_json(folder / "providers-without-secrets.json", providers)
            manifest = {
                "version": 1,
                "backup_id": str(row.id),
                "created_at": now().isoformat(),
                "database": {
                    "file": "database.dump",
                    "sha256": digest_file(dump_database_path),
                    "format": "PostgreSQL custom",
                },
                "assets": manifest_assets,
                "included": [
                    "records",
                    "relationships",
                    "notes",
                    "user corrections",
                    "extraction revisions",
                    "original files",
                    "settings without provider secrets",
                ],
                "excluded": [
                    "provider credentials",
                    "encryption key",
                    "database password",
                    "search chunks/vectors",
                    "previews",
                    "models",
                    "temporary exports",
                ],
                "restore": "Fresh database only. Rebuild previews/search; reconnect providers and issue fresh agent tokens.",
            }
            private_json(folder / "manifest.json", manifest)
            # Only manifest-listed assets are restored; remove pre-copy files deleted before the snapshot.
            allowed = {item["path"] for item in manifest_assets}
            for file in originals.rglob("*"):
                if file.is_file() and str(file.relative_to(originals)) not in allowed:
                    file.unlink()
        row = db.get(Backup, row.id)
        row.state, row.finished_at, row.path = (
            "complete",
            now(),
            str(folder.relative_to(settings.backup_dir)),
        )
        row.bytes = sum(file.stat().st_size for file in folder.rglob("*") if file.is_file())
        db.commit()
    except Exception:
        db.rollback()
        if folder.is_dir() and all(status.ok for status in guard.check(force=True)):
            shutil.rmtree(folder)
        row = db.get(Backup, row.id)
        row.state, row.finished_at, row.error = (
            "failed",
            now(),
            "Backup failed. Check the backup/originals drives, free space and database access. Existing complete backups are kept.",
        )
        db.commit()
        raise RuntimeError(row.error) from None
    # Outside the try: a retention problem must never delete or fail the snapshot just made.
    try:
        prune(db, settings)
    except Exception:
        db.rollback()
        logging.getLogger("worker").warning(
            "backup_prune_failed", extra={"event": "backup_prune_failed"}
        )
    return row


def prune(db, settings):
    config = configuration(db)
    rows = list(db.scalars(select(Backup).where(Backup.state == "complete")))
    keep = retained(rows, config["daily_keep"], config["weekly_keep"])
    for row in rows:
        if row.id not in keep:
            path = asset_path(settings.backup_dir, row.path)
            if path.parent != settings.backup_dir / "snapshots" or path.name != str(row.id):
                raise RuntimeError("Invalid backup path; retention stopped.")
            if path.exists():
                shutil.rmtree(path)
            row.state = "expired"
    db.commit()


def main():
    settings = Settings()
    with Session(build_engine(settings), expire_on_commit=False) as db:
        row = Backup(trigger="manual")
        db.add(row)
        db.commit()
        run_backup(db, row, settings)
        print(f"Backup complete: {row.path}")


if __name__ == "__main__":
    main()
