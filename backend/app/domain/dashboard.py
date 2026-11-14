from datetime import timedelta

from sqlalchemy import func, or_, select

from app.db.capture import CaptureGroup, QueueReport
from app.db.intelligence import Appearance, EditHistory, ProviderSetting
from app.db.library import Document, Note, Owner, now
from app.db.processing import Job
from app.domain.review import document_status, pending


def summary(db, expo_id=None, *, include_notes=True, settings=None):
    from app.api.library import record
    from app.api.providers import public

    conditions = [Document.deleted_at.is_(None)]
    if expo_id:
        conditions.append(Document.expo_id == expo_id)
    docs = select(Document.id).where(*conditions)
    appearances = select(Appearance).where(Appearance.document_id.in_(docs))
    counts = dict(
        db.execute(
            select(Document.processing_state, func.count())
            .where(*conditions)
            .group_by(Document.processing_state)
        ).all()
    )
    company_ids = select(Appearance.company_id).where(Appearance.document_id.in_(docs))
    notes = select(func.count(Note.id)).where(Note.deleted_at.is_(None))
    if expo_id:
        notes = notes.where(
            or_(
                Note.expo_id == expo_id,
                Note.document_id.in_(docs),
                Note.company_id.in_(company_ids),
                Note.capture_group_id.in_(
                    select(CaptureGroup.id).where(CaptureGroup.expo_id == expo_id)
                ),
            )
        )
    cloud_allowed = (db.scalar(select(Owner.settings)) or {}).get("cloud_fallback", False)
    proposals = pending(db, expo_id)
    recent = [
        {**record(doc), **document_status(db, doc, proposals)}
        for doc in db.scalars(
            select(Document).where(*conditions).order_by(Document.created_at.desc()).limit(6)
        )
    ]
    provider_states = []
    for row in db.scalars(select(ProviderSetting).order_by(ProviderSetting.order)):
        state = public(row, settings)
        state["connected"] = any(
            account["id"] == state["active_account"] and account["connected"]
            for account in state.pop("accounts")
        )
        state.pop("active_account")
        state["processing_allowed"] = row.enabled and (
            cloud_allowed or (row.provider == "ollama" and not row.config.get("remote", False))
        )
        provider_states.append(state)
    return {
        "proposed_changes": len(proposals),
        "documents": sum(counts.values()),
        "companies": db.scalar(
            select(func.count(func.distinct(appearances.subquery().c.company_id)))
        ),
        "contacts": db.scalar(
            select(func.count(func.distinct(appearances.subquery().c.contact_id)))
        ),
        "notes": db.scalar(notes) if include_notes else None,
        "processing": counts,
        "grouping": db.scalar(
            select(func.count(Document.id)).where(*conditions, Document.group_state == "suggested")
        ),
        "grouping_overdue": db.scalar(
            select(func.count(Document.id)).where(
                *conditions,
                Document.group_state == "suggested",
                Document.created_at < now() - timedelta(days=3),
            )
        ),
        "review": sum(
            document_status(db, doc, proposals)["review_status"] == "needs_attention"
            for doc in db.scalars(select(Document).where(*conditions))
        ),
        "failed": counts.get("failed", 0),
        "waiting_reason": db.scalar(
            select(Job.error)
            .where(Job.kind == "ai", Job.state == "waiting")
            .order_by(Job.updated_at.desc())
            .limit(1)
        ),
        "recent": recent,
        "phone_queue": [
            record(row)
            for row in db.scalars(
                select(QueueReport)
                .where(or_(QueueReport.files > 0, QueueReport.notes > 0))
                .order_by(QueueReport.updated_at.desc())
                .limit(20)
            )
        ],
        "providers": provider_states,
        "activity": [
            {"kind": "edit", "actor": row.actor, "field": row.field, "created_at": row.created_at}
            for row in db.scalars(
                select(EditHistory).order_by(EditHistory.created_at.desc()).limit(5)
            )
        ],
    }
