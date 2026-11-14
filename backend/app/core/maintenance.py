"""PostgreSQL write barrier shared by requests, jobs and backup snapshots."""

from sqlalchemy import event, text
from sqlalchemy.orm import Session

WRITE_LOCK = 752682014019


def lock_writes(db):
    db.info["library_write"] = True
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock_shared(:key)"), {"key": WRITE_LOCK})


@event.listens_for(Session, "after_begin")
def on_transaction(db, transaction, connection):
    if (
        db.info.get("library_write")
        and not db.info.get("backup_metadata")
        and connection.dialect.name == "postgresql"
    ):
        connection.execute(text("SELECT pg_advisory_xact_lock_shared(:key)"), {"key": WRITE_LOCK})


@event.listens_for(Session, "before_flush")
def on_write(db, flush_context, instances):
    if not db.info.get("backup_metadata") and (db.new or db.dirty or db.deleted):
        lock_writes(db)
