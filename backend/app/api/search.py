from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.dependencies import DB, OwnerSession
from app.api.library import find, record
from app.db.intelligence import Appearance, TagLink
from app.db.library import Document, Expo
from app.db.processing import SearchChunk
from app.db.search import BulkAction, SavedSearch
from app.domain import tags
from app.domain.jobs import enqueue

router = APIRouter(prefix="/api/v1", tags=["search and bulk"])


class SaveSearch(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    query: str = Field(min_length=1, max_length=500)
    filters: dict = Field(default_factory=dict)


@router.get("/saved-searches")
def saved_searches(session: OwnerSession, db: DB):
    return [record(row) for row in db.scalars(select(SavedSearch).order_by(SavedSearch.name))]


@router.post("/saved-searches", status_code=201)
def save_search(body: SaveSearch, session: OwnerSession, db: DB):
    row = SavedSearch(**body.model_dump())
    db.add(row)
    db.commit()
    return record(row)


@router.delete("/saved-searches/{id}")
def delete_search(id: UUID, session: OwnerSession, db: DB):
    db.delete(find(db, SavedSearch, id))
    db.commit()
    return {"saved": True}


class Bulk(BaseModel):
    action: str = Field(pattern="^(tag|move_expo|review|trash)$")
    document_ids: list[UUID] = Field(min_length=1, max_length=1000)
    expo_id: UUID | None = None
    labels: list[str] = Field(default_factory=list, max_length=100)


def bulk_state(doc):
    return {
        "expo_id": str(doc.expo_id),
        "review_state": doc.review_state,
        "review_reasons": doc.review_reasons,
        "deleted_at": doc.deleted_at.isoformat() if doc.deleted_at else None,
    }


@router.post("/bulk")
def bulk(body: Bulk, session: OwnerSession, db: DB):
    from app.db.library import now

    docs = [find(db, Document, id) for id in set(body.document_ids)]
    before = {str(doc.id): bulk_state(doc) for doc in docs}
    links_before = set(db.scalars(select(TagLink.id))) if body.action == "tag" else set()
    if body.action == "move_expo":
        if not body.expo_id:
            raise HTTPException(422, "Choose an expo.")
        find(db, Expo, body.expo_id)
    for doc in docs:
        if body.action == "trash":
            doc.deleted_at = now()
        elif body.action == "review":
            from app.domain.review import for_document

            if for_document(db, doc):
                raise HTTPException(
                    409, "Decide the outstanding suggestions before marking documents reviewed."
                )
            doc.review_state = "reviewed"
            doc.review_reasons = []
        elif body.action == "move_expo":
            doc.expo_id = body.expo_id
            for row in db.scalars(select(Appearance).where(Appearance.document_id == doc.id)):
                row.expo_id = body.expo_id
            for row in db.scalars(select(SearchChunk).where(SearchChunk.document_id == doc.id)):
                row.expo_id = body.expo_id
        else:
            tags.assign(db, "document", doc.id, body.labels)
    db.flush()
    added = (
        [str(id) for id in set(db.scalars(select(TagLink.id))) - links_before]
        if body.action == "tag"
        else []
    )
    row = BulkAction(
        kind=body.action,
        before={"documents": before, "added_tags": added},
        after={str(doc.id): bulk_state(doc) for doc in docs},
    )
    db.add(row)
    db.commit()
    return {"action_id": row.id, "count": len(docs)}


@router.post("/bulk/{id}/undo")
def undo_bulk(id: UUID, session: OwnerSession, db: DB):
    action = find(db, BulkAction, id)
    if action.state == "undone":
        return {"saved": True}
    for id, values in action.before["documents"].items():
        doc = find(db, Document, UUID(id))
        if bulk_state(doc) != action.after[id]:
            raise HTTPException(409, "One of these documents changed. Review it before undoing.")
        doc.expo_id = UUID(values["expo_id"])
        doc.review_state = values["review_state"]
        doc.review_reasons = values.get("review_reasons", doc.review_reasons)
        doc.deleted_at = (
            datetime.fromisoformat(values["deleted_at"]) if values["deleted_at"] else None
        )
        for row in db.scalars(select(Appearance).where(Appearance.document_id == doc.id)):
            row.expo_id = doc.expo_id
        for row in db.scalars(select(SearchChunk).where(SearchChunk.document_id == doc.id)):
            row.expo_id = doc.expo_id
    for id in action.before["added_tags"]:
        if row := db.get(TagLink, UUID(id)):
            db.delete(row)
    action.state = "undone"
    db.commit()
    return {"saved": True}


@router.post("/system/reindex")
def rebuild_search(request: Request, session: OwnerSession, db: DB):
    import time

    job = enqueue(db, "reindex", request.app.state.settings.host_id, int(time.time()))
    db.commit()
    return {"job_id": job.id}
