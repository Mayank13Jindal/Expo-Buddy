from datetime import timedelta
from uuid import UUID

from sqlalchemy import and_, case, or_, select
from sqlalchemy.orm import Session

from app.db.library import now
from app.db.processing import Job


class WaitForResource(Exception):
    pass


def enqueue(
    db: Session,
    kind: str,
    target: UUID,
    revision: int,
    *,
    pool: str = "local",
    params: dict | None = None,
) -> Job:
    existing = db.scalar(
        select(Job).where(Job.kind == kind, Job.target_id == target, Job.input_revision == revision)
    )
    if existing:
        return existing
    job = Job(kind=kind, target_id=target, input_revision=revision, pool=pool, input=params or {})
    db.add(job)
    db.flush()
    return job


def claim(db: Session, pool: str, worker_id: str, lease_seconds: int = 120) -> Job | None:
    current = now()
    job = db.scalar(
        select(Job)
        .where(
            Job.pool == pool,
            or_(
                and_(Job.state.in_(("queued", "waiting")), Job.next_run_at <= current),
                and_(Job.state == "running", Job.lease_until <= current),
            ),
        )
        .order_by(
            case((Job.kind.in_(("export", "backup")), 0), (Job.kind == "embed", 2), else_=1),
            Job.next_run_at,
            Job.created_at,
        )
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job:
        job.state = "running"
        job.attempts += 1
        job.worker_id = worker_id
        job.lease_until = current + timedelta(seconds=lease_seconds)
        db.commit()
    return job


def fail_or_retry(db: Session, job: Job, reason: str, *, waiting: bool = False) -> None:
    job.error = reason[:500]
    job.lease_until = None
    if waiting:
        job.attempts = max(0, job.attempts - 1)
        job.state = "waiting"
        delay = 60
    elif job.attempts >= 5:
        job.state = "failed"
        delay = 0
    else:
        job.state = "queued"
        delay = min(300, 2**job.attempts * 5)
    job.next_run_at = now() + timedelta(seconds=delay)
    db.commit()
