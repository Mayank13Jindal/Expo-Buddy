from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.dependencies import DB, OwnerSession
from app.api.library import find, record
from app.db.grouping import GroupingAction
from app.db.library import Document, DocumentPage
from app.domain import grouping

router = APIRouter(prefix="/api/v1/grouping", tags=["grouping"])


@router.get("")
def inbox(
    session: OwnerSession,
    db: DB,
    batch: Annotated[UUID | None, Query(alias="session")] = None,
    expo_id: UUID | None = None,
):
    statement = select(Document).where(
        Document.group_state == "suggested", Document.deleted_at.is_(None)
    )
    if batch:
        statement = statement.where(Document.upload_session_id == batch)
    if expo_id:
        statement = statement.where(Document.expo_id == expo_id)
    documents = list(db.scalars(statement.order_by(Document.created_at)))
    groups = {}
    for doc in documents:
        groups.setdefault(str(doc.upload_session_id), []).append(doc)
    return {
        "batches": [
            {
                "id": id,
                "documents": [
                    {
                        **record(doc),
                        "pages": [
                            record(page)
                            for page in db.scalars(
                                select(DocumentPage)
                                .where(DocumentPage.document_id == doc.id)
                                .order_by(DocumentPage.order)
                            )
                        ],
                    }
                    for doc in docs
                ],
                "suggestions": grouping.suggest(db, docs),
            }
            for id, docs in groups.items()
        ]
    }


class Selection(BaseModel):
    document_ids: list[UUID] = Field(min_length=1, max_length=1000)


def selected(db: DB, ids: list[UUID]) -> list[Document]:
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "Choose each document once.")
    documents = [find(db, Document, id) for id in ids]
    if any(
        doc.deleted_at or doc.processing_state not in ("waiting_grouping", "waiting_ai", "ready")
        for doc in documents
    ):
        raise HTTPException(409, "Wait for text reading to finish before checking these groups.")
    return documents


@router.post("/accept")
def accept(body: Selection, session: OwnerSession, db: DB):
    documents = selected(db, body.document_ids)
    action = grouping.snapshot(db, documents, "accept")
    target = grouping.combine(db, documents)
    grouping.confirm(db, target)
    grouping.finish_action(db, action, documents)
    db.commit()
    return {"action_id": action.id, "document_id": target.id}


class Batch(BaseModel):
    upload_session_id: UUID


@router.post("/accept-all")
def accept_all(body: Batch, session: OwnerSession, db: DB):
    documents = grouping.documents_for_batch(db, body.upload_session_id)
    documents = selected(db, [doc.id for doc in documents])
    action = grouping.snapshot(db, documents, "accept_all")
    mapping = {str(doc.id): doc for doc in documents}
    for suggestion in grouping.suggest(db, documents):
        target = grouping.combine(db, [mapping[id] for id in suggestion["document_ids"]])
        grouping.confirm(db, target)
    grouping.finish_action(db, action, documents)
    db.commit()
    return {"action_id": action.id, "count": len(documents)}


@router.post("/keep-separate")
def keep_separate(body: Batch, session: OwnerSession, db: DB):
    documents = selected(
        db, [doc.id for doc in grouping.documents_for_batch(db, body.upload_session_id)]
    )
    action = grouping.snapshot(db, documents, "keep_separate")
    for doc in documents:
        grouping.confirm(db, doc)
    grouping.finish_action(db, action, documents)
    db.commit()
    return {"action_id": action.id}


@router.post("/combine")
def combine(body: Selection, session: OwnerSession, db: DB):
    documents = selected(db, body.document_ids)
    action = grouping.snapshot(db, documents, "combine")
    target = grouping.combine(db, documents)
    target.group_state = "suggested"
    target.processing_state = "waiting_grouping"
    grouping.finish_action(db, action, documents)
    db.commit()
    return {"action_id": action.id, "document_id": target.id}


class Split(BaseModel):
    document_id: UUID
    page_ids: list[UUID] = Field(min_length=1, max_length=200)


@router.post("/split")
def split(body: Split, session: OwnerSession, db: DB):
    document = selected(db, [body.document_id])[0]
    pages = list(
        db.scalars(
            select(DocumentPage)
            .where(DocumentPage.document_id == document.id)
            .order_by(DocumentPage.order)
        )
    )
    chosen = [page for page in pages if page.id in body.page_ids]
    if len(chosen) != len(set(body.page_ids)) or len(chosen) >= len(pages):
        raise HTTPException(422, "Choose some pages to split, leaving at least one page here.")
    action = grouping.snapshot(db, [document], "split")
    created = Document(
        expo_id=document.expo_id,
        upload_session_id=document.upload_session_id,
        title=document.title + " — split",
        type=document.type,
        processing_state="waiting_grouping",
    )
    db.add(created)
    db.flush()
    grouping.reorder(db, chosen, created)
    grouping.reorder(db, [page for page in pages if page not in chosen])
    document.revision += 1
    document.group_state = "suggested"
    document.processing_state = "waiting_grouping"
    action.snapshot = {**action.snapshot, "created_ids": [str(created.id)]}
    grouping.finish_action(db, action, [document, created])
    db.commit()
    return {"action_id": action.id, "document_id": created.id}


class Reorder(BaseModel):
    document_id: UUID
    page_ids: list[UUID] = Field(min_length=1, max_length=200)
    roles: dict[UUID, str] = Field(default_factory=dict)


@router.post("/reorder")
def reorder(body: Reorder, session: OwnerSession, db: DB):
    document = selected(db, [body.document_id])[0]
    pages = list(db.scalars(select(DocumentPage).where(DocumentPage.document_id == document.id)))
    if (
        len(body.page_ids) != len(pages)
        or len(set(body.page_ids)) != len(pages)
        or set(body.page_ids) != {page.id for page in pages}
    ):
        raise HTTPException(422, "Include every page once.")
    if any(role not in ("front", "back", "page") for role in body.roles.values()):
        raise HTTPException(422, "Use front, back or page.")
    action = grouping.snapshot(db, [document], "reorder")
    mapping = {page.id: page for page in pages}
    grouping.reorder(db, [mapping[id] for id in body.page_ids])
    for id, role in body.roles.items():
        mapping[id].role = role
    document.revision += 1
    grouping.finish_action(db, action, [document])
    db.commit()
    return {"action_id": action.id}


class Undo(BaseModel):
    action_id: UUID


@router.post("/undo")
def undo(body: Undo, session: OwnerSession, db: DB):
    grouping.undo(db, find(db, GroupingAction, body.action_id))
    db.commit()
    return {"saved": True}
