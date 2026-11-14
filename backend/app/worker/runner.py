"""Leased CPU/AI job pools, scheduling, health and local embedding service."""

import logging
import multiprocessing
import signal
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import Engine, delete, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import configure_logging
from app.core.storage import StorageGuard, configured_volumes
from app.db.agent import AgentAudit
from app.db.library import Document, now
from app.db.models import RuntimeHeartbeat
from app.db.processing import Job
from app.db.session import build_engine
from app.domain.jobs import claim, fail_or_retry
from app.worker.jobs import execute_job

log = logging.getLogger("worker")


def heartbeat(engine: Engine, state: str) -> None:
    now = datetime.now(UTC)
    statement = (
        insert(RuntimeHeartbeat)
        .values(
            id=uuid4(),
            role="worker",
            state=state,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=[RuntimeHeartbeat.role],
            set_={"state": state, "updated_at": now},
        )
    )
    with engine.begin() as connection:
        connection.execute(statement)


def maintain(engine: Engine, settings: Settings) -> None:
    from app.domain.backups import schedule
    from app.exports.package import expire

    with Session(engine) as db:
        expire(db, settings)
        schedule(db, settings)
        db.execute(delete(AgentAudit).where(AgentAudit.created_at < now() - timedelta(days=90)))
        db.commit()


def main() -> None:
    configure_logging()
    settings = Settings()
    guard = StorageGuard(configured_volumes(settings), interval=settings.storage_check_seconds)
    guard.require_ready()
    import tempfile

    temporary = settings.previews_dir / ".tmp"
    temporary.mkdir(exist_ok=True, mode=0o700)
    tempfile.tempdir = str(temporary)
    _ = settings.host_id
    engine = build_engine(settings)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    log.info("worker_started", extra={"event": "worker_started"})
    from app.worker.embedding_server import start

    embedding_server = start(settings)
    worker_id = str(uuid4())
    pools = {
        name: ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
        for name in ("local", "ai")
    }
    active = {}
    last_maintenance = 0.0
    try:
        while not stop.is_set():
            state = "ready" if all(volume.ok for volume in guard.check()) else "paused"
            try:
                heartbeat(engine, state)
                if state == "ready" and time.monotonic() - last_maintenance > 60:
                    last_maintenance = time.monotonic()
                    # Own try: a cleanup failure must not stop job pickup below.
                    try:
                        maintain(engine, settings)
                    except Exception:
                        log.warning("maintenance_failed", extra={"event": "maintenance_failed"})
                for name, pool in pools.items():
                    with Session(engine, expire_on_commit=False) as db:
                        if name in active:
                            job_id, future = active[name]
                            if future.done():
                                try:
                                    future.result()
                                except Exception:
                                    job = db.get(Job, job_id)
                                    if job and job.state == "running":
                                        fail_or_retry(
                                            db, job, "The worker stopped. This task will retry."
                                        )
                                del active[name]
                            else:
                                db.execute(
                                    update(Job)
                                    .where(
                                        Job.id == job_id,
                                        Job.worker_id == worker_id,
                                        Job.state == "running",
                                    )
                                    .values(lease_until=now() + timedelta(seconds=120))
                                )
                                db.commit()
                        if state == "ready" and name not in active:
                            job = claim(db, name, worker_id)
                            if job:
                                document = db.get(Document, job.target_id)
                                if document:
                                    document.processing_state = {
                                        "prepare": "preparing",
                                        "read": "reading",
                                        "ai": "waiting_ai",
                                        "embed": "indexing",
                                    }.get(job.kind, document.processing_state)
                                    db.commit()
                                active[name] = (job.id, pool.submit(execute_job, job.id, worker_id))
            except Exception:
                log.warning("heartbeat_failed", extra={"event": "heartbeat_failed"})
            stop.wait(settings.worker_interval_seconds)
    finally:
        embedding_server.shutdown()
        for pool in pools.values():
            pool.shutdown(wait=False, cancel_futures=True)
        engine.dispose()


if __name__ == "__main__":
    main()
