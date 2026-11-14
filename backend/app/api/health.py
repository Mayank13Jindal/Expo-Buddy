import logging
from datetime import UTC, datetime

from sqlalchemy import Engine, text

from app.core.config import Settings
from app.core.storage import StorageGuard

SCHEMA_REVISION = "0012_capture_options"


def read_health(engine: Engine, storage: StorageGuard, settings: Settings) -> dict:
    disks = storage.check()
    database = "unavailable"
    schema = "unavailable"
    worker = "unavailable"
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            database = "ready"
            current = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
            schema = "ready" if current == SCHEMA_REVISION else "migration_needed"
            heartbeat = connection.execute(
                text("SELECT updated_at, state FROM runtime_heartbeats WHERE role = 'worker'")
            ).first()
            if heartbeat:
                age = (datetime.now(UTC) - heartbeat.updated_at).total_seconds()
                if age <= settings.worker_stale_seconds:
                    worker = "ready" if heartbeat.state == "ready" else "paused"
                else:
                    worker = "stale"
    except Exception:
        # Never return DB connection errors: these may include connection credentials.
        logging.getLogger("health").warning(
            "health_check_failed", extra={"event": "health_check_failed"}
        )

    storage_ok = all(disk.ok for disk in disks)
    ready = database == schema == worker == "ready" and storage_ok
    return {
        "status": "ready" if ready else "unavailable",
        "stage": 9,
        "release_ready": False,
        "services": {"database": database, "schema": schema, "worker": worker},
        "storage": [
            {
                "name": disk.name,
                "status": "ready" if disk.ok else "unavailable",
                "message": disk.message,
                "warning": disk.warning,
            }
            for disk in disks
        ],
        "canonical_url": settings.canonical_origin,
        "message": "Service availability; AI provider availability is reported separately.",
    }
