from datetime import UTC, datetime

from sqlalchemy import text

from app.core.config import Settings
from app.core.storage import StorageGuard, configured_volumes
from app.db.session import build_engine


def main() -> int:
    settings = Settings()
    StorageGuard(configured_volumes(settings)).require_ready()
    engine = build_engine(settings)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text("SELECT updated_at, state FROM runtime_heartbeats WHERE role = 'worker'")
            ).first()
        return (
            0
            if (
                row
                and row.state == "ready"
                and (datetime.now(UTC) - row.updated_at).total_seconds()
                < settings.worker_stale_seconds
            )
            else 1
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
