import re
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.grouping import GroupingAction
from app.db.library import Asset, Document, DocumentPage, Note, now
from app.db.processing import Job, OCRResult, SearchChunk
from app.domain.jobs import enqueue
from app.pipeline.index import index_note


def documents_for_batch(db: Session, batch: UUID) -> list[Document]:
    return list(
        db.scalars(
            select(Document)
            .where(Document.upload_session_id == batch, Document.deleted_at.is_(None))
            .order_by(Document.created_at)
            .with_for_update()
        )
    )


def suggest(db: Session, documents: list[Document]) -> list[dict]:
    groups = []
    for doc in documents:
        pages = list(
            db.scalars(
                select(DocumentPage)
                .where(DocumentPage.document_id == doc.id)
                .order_by(DocumentPage.order)
            )
        )
        assets = [db.get(Asset, page.asset_id) for page in pages]
        texts = list(
            db.scalars(
                select(OCRResult.text).join(DocumentPage).where(DocumentPage.document_id == doc.id)
            )
        )
        text = "\n".join(texts).lower()
        signals = set(re.findall(r"[\w.+-]+@([\w.-]+\.[a-z]{2,})", text))
        signals |= {re.sub(r"\D", "", value) for value in re.findall(r"\+?[\d ()-]{8,}\d", text)}
        from app.domain.capture import groups_for_document

        booths = {str(id) for id in groups_for_document(db, doc.id)}
        stem = (
            re.sub(
                r"[-_ ]?(front|back|[12])$",
                "",
                assets[0].original_filename.rsplit(".", 1)[0].lower(),
            )
            if assets
            else ""
        )
        candidate = None
        reason = "Each file starts as its own document."
        if groups and len(pages) == 1:
            previous = groups[-1]
            if booths & previous["booths"]:
                candidate, reason = previous, "Captured at the same booth."
            elif signals & previous["signals"]:
                candidate, reason = previous, "Adjacent files share a phone number or email domain."
            elif (
                stem
                and stem == previous["stem"]
                and any(word in (assets[0].original_filename.lower()) for word in ("front", "back"))
            ):
                candidate, reason = previous, "Adjacent filenames suggest a front and back."
        if candidate:
            candidate["document_ids"].append(str(doc.id))
            candidate["reason"] = reason
            candidate["signals"] |= signals
            candidate["booths"] |= booths
        else:
            groups.append(
                {
                    "document_ids": [str(doc.id)],
                    "reason": reason,
                    "signals": signals,
                    "booths": booths,
                    "stem": stem,
                }
            )
    return [{"document_ids": group["document_ids"], "reason": group["reason"]} for group in groups]


def snapshot(db: Session, documents: list[Document], kind: str) -> GroupingAction:
    ids = [doc.id for doc in documents]
    pages = list(db.scalars(select(DocumentPage).where(DocumentPage.document_id.in_(ids))))
    notes = list(db.scalars(select(Note).where(Note.document_id.in_(ids))))
    action = GroupingAction(
        kind=kind,
        upload_session_id=documents[0].upload_session_id if documents else None,
        snapshot={
            "documents": [
                {
                    "id": str(doc.id),
                    "title": doc.title,
                    "type": doc.type,
                    "group_state": doc.group_state,
                    "processing_state": doc.processing_state,
                    "revision": doc.revision,
                    "company_id": str(doc.company_id) if doc.company_id else None,
                    "deleted_at": doc.deleted_at.isoformat() if doc.deleted_at else None,
                }
                for doc in documents
            ],
            "pages": [
                {
                    "id": str(page.id),
                    "document_id": str(page.document_id),
                    "order": page.order,
                    "role": page.role,
                }
                for page in pages
            ],
            "notes": [{"id": str(note.id), "document_id": str(note.document_id)} for note in notes],
            "created_ids": [],
        },
    )
    db.add(action)
    db.flush()
    return action


def finish_action(db: Session, action: GroupingAction, documents: list[Document]) -> None:
    action.after_revisions = {str(doc.id): doc.revision for doc in documents}
    db.flush()


def reorder(db: Session, pages: list[DocumentPage], target: Document | None = None) -> None:
    for index, page in enumerate(pages):
        page.order = -100000 - index
    db.flush()
    if target:
        for page in pages:
            page.document_id = target.id
        db.flush()
    for index, page in enumerate(pages):
        page.order = index
    db.flush()


def combine(db: Session, documents: list[Document]) -> Document:
    if not documents:
        raise HTTPException(422, "Choose at least one document.")
    if len({doc.expo_id for doc in documents}) != 1:
        raise HTTPException(422, "Combine files from the same expo.")
    target, *others = documents
    if not others:
        return target
    pages = []
    for doc in documents:
        pages.extend(
            db.scalars(
                select(DocumentPage)
                .where(DocumentPage.document_id == doc.id)
                .order_by(DocumentPage.order)
            )
        )
    reorder(db, pages, target)
    for doc in others:
        for note in db.scalars(select(Note).where(Note.document_id == doc.id)):
            note.document_id = target.id
            index_note(db, note)
        db.execute(
            update(SearchChunk)
            .where(SearchChunk.document_id == doc.id)
            .values(document_id=target.id)
        )
        db.execute(
            update(Job)
            .where(Job.target_id == doc.id, Job.state.in_(("queued", "waiting")))
            .values(state="cancelled")
        )
        doc.deleted_at = now()
        doc.revision += 1
    target.revision += 1
    return target


def confirm(db: Session, document: Document) -> None:
    document.group_state = "confirmed"
    document.processing_state = "waiting_ai"
    if document.processing_options.get("image_check"):
        enqueue(db, "vision", document.id, document.revision, pool="ai")
    enqueue(db, "ai", document.id, document.revision, pool="ai")


def undo(db: Session, action: GroupingAction) -> None:
    if action.undone_at:
        return
    for id, revision in action.after_revisions.items():
        current = db.get(Document, UUID(id))
        if current and current.revision != revision:
            raise HTTPException(
                409, "These groups have changed. Use Split or Combine to adjust them."
            )
    pages = [db.get(DocumentPage, UUID(row["id"])) for row in action.snapshot["pages"]]
    for index, page in enumerate(pages):
        page.order = -200000 - index
    db.flush()
    for values in action.snapshot["pages"]:
        page = db.get(DocumentPage, UUID(values["id"]))
        page.document_id, page.role = UUID(values["document_id"]), values["role"]
    db.flush()
    for values in action.snapshot["pages"]:
        db.get(DocumentPage, UUID(values["id"])).order = values["order"]
    for values in action.snapshot["documents"]:
        doc = db.get(Document, UUID(values["id"]))
        # Group undo must not undo a later user correction to a title/type.
        from app.db.intelligence import FieldValue

        for field in ("title", "type"):
            corrected = db.scalar(
                select(FieldValue.id).where(
                    FieldValue.entity_id == doc.id,
                    FieldValue.field == field,
                    FieldValue.is_current.is_(True),
                    FieldValue.source == "user",
                )
            )
            if not corrected:
                setattr(doc, field, values[field])
        doc.group_state = values["group_state"]
        doc.processing_state = values["processing_state"]
        doc.company_id = UUID(values["company_id"]) if values["company_id"] else None
        doc.deleted_at = None
        doc.revision += 1
        db.execute(
            update(Job)
            .where(Job.target_id == doc.id, Job.state.in_(("queued", "waiting")))
            .values(state="cancelled")
        )
    for id in action.snapshot["created_ids"]:
        db.get(Document, UUID(id)).deleted_at = now()
    for values in action.snapshot["notes"]:
        note = db.get(Note, UUID(values["id"]))
        note.document_id = UUID(values["document_id"])
        index_note(db, note)
    for page in pages:
        db.execute(
            update(SearchChunk)
            .where(SearchChunk.page_id == page.id)
            .values(document_id=page.document_id)
        )
    action.undone_at = now()
    db.flush()
