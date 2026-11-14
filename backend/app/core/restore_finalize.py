"""Finalize a freshly restored database; never changes the configured DB name."""

import argparse
import json
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db import (  # noqa: F401
    agent,
    capture,
    exports,
    grouping,
    intelligence,
    library,
    operations,
    processing,
    search,
)
from app.db.agent import APIToken
from app.db.intelligence import ProviderSetting
from app.db.library import Document, Owner, now
from app.db.library import Session as OwnerSession
from app.db.operations import Backup
from app.db.processing import Job
from app.db.session import build_engine
from app.domain.jobs import enqueue
from app.pipeline.index import rebuild_index


def finalize(db, provider_data):
    from sqlalchemy import delete

    db.execute(delete(OwnerSession))
    db.execute(update(APIToken).values(revoked_at=now(), calls=0))
    for owner in db.scalars(select(Owner)):
        owner.settings = {**owner.settings, "cloud_fallback": False}
    for data in provider_data:
        row = db.scalar(select(ProviderSetting).where(ProviderSetting.provider == data["provider"]))
        if not row:
            row = ProviderSetting(
                id=UUID(data["id"]), provider=data["provider"], order=data["order"]
            )
            db.add(row)
        row.enabled, row.encrypted_secret, row.last_status = False, None, "reconnect_required"
        row.model, row.config = data.get("model", ""), data.get("config", {})
        row.spending_cap, row.spent, row.reserved = (
            Decimal(data.get("spending_cap", "0")),
            Decimal(data.get("spent", "0")),
            Decimal(0),
        )
        row.month, row.cooldown_until = data.get("month", ""), None
    db.execute(
        update(Job)
        .where(Job.state == "running")
        .values(state="queued", worker_id=None, lease_until=None, next_run_at=now(), attempts=0)
    )
    db.execute(
        update(Job)
        .where(Job.kind.in_(("embed", "export", "backup", "purge")))
        .values(state="cancelled", lease_until=None)
    )
    for row in db.scalars(select(Backup).where(Backup.state.in_(("queued", "running")))):
        row.state, row.finished_at, row.error = (
            "failed",
            now(),
            "This backup was in progress in the restored snapshot. Make a fresh backup on this server.",
        )
    rebuild_index(db)
    for doc in db.scalars(select(Document).where(Document.deleted_at.is_(None))):
        job = enqueue(db, "rebuild_previews", doc.id, doc.revision)
        job.state, job.next_run_at, job.lease_until, job.attempts = "queued", now(), None, 0
    db.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("providers_json", type=Path)
    args = parser.parse_args()
    settings = Settings()
    with Session(build_engine(settings)) as db:
        finalize(db, json.loads(args.providers_json.read_text()))
    print(
        "Restored records indexed. Previews queued. Sessions cleared, agent tokens revoked, provider credentials absent."
    )


if __name__ == "__main__":
    main()
