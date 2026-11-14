from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.dependencies import DB, OwnerSession
from app.api.library import find
from app.db.library import Document
from app.domain import trash

router = APIRouter(prefix="/api/v1/documents", tags=["trash"])


@router.get("/{id}/permanent-removal")
def removal_preview(id: UUID, session: OwnerSession, db: DB):
    return trash.preview(db, find(db, Document, id))


class ConfirmRemoval(BaseModel):
    confirmation: str


@router.post("/{id}/permanent-removal", status_code=202)
def remove(id: UUID, body: ConfirmRemoval, session: OwnerSession, db: DB):
    job = trash.queue_removal(db, find(db, Document, id), body.confirmation)
    db.commit()
    return {"job_id": job.id, "state": "queued"}
