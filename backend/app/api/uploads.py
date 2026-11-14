from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.dependencies import DB, OwnerSession
from app.api.library import find, record
from app.db.library import Asset, Document, Expo, UploadSession
from app.domain.uploads import asset_path, receive_file

router = APIRouter(prefix="/api/v1", tags=["uploads"])


class UploadInput(BaseModel):
    expo_id: UUID
    device_label: str = Field(default="Browser", max_length=100)
    client_uuid: UUID | None = None


@router.post("/upload-sessions", status_code=201)
def create_session(body: UploadInput, session: OwnerSession, db: DB):
    find(db, Expo, body.expo_id)
    if body.client_uuid and (
        existing := db.scalar(
            select(UploadSession).where(UploadSession.client_uuid == body.client_uuid)
        )
    ):
        if existing.expo_id != body.expo_id:
            raise HTTPException(409, "An upload session keeps its original expo.")
        return record(existing)
    upload = UploadSession(**body.model_dump())
    db.add(upload)
    db.commit()
    return record(upload)


@router.get("/upload-sessions/{id}")
def get_session(id: UUID, session: OwnerSession, db: DB):
    upload = find(db, UploadSession, id)
    return {
        **record(upload),
        "saved_count": db.scalar(
            select(func.count(Document.id)).where(Document.upload_session_id == id)
        ),
    }


class Hashes(BaseModel):
    sha256: list[str] = Field(max_length=1000)


@router.post("/upload-sessions/{id}/check")
def check_existing(id: UUID, body: Hashes, session: OwnerSession, db: DB):
    find(db, UploadSession, id)
    return {
        "existing": {
            asset.sha256: str(asset.id)
            for asset in db.scalars(
                select(Asset).where(Asset.sha256.in_(body.sha256), Asset.purged_at.is_(None))
            )
        }
    }


@router.post("/upload-sessions/{id}/files", status_code=201)
async def upload_file(
    id: UUID,
    request: Request,
    session: OwnerSession,
    db: DB,
    file: Annotated[UploadFile | None, File()] = None,
    sha256: Annotated[str | None, Form()] = None,
    client_uuid: Annotated[UUID | None, Form()] = None,
    kind: Annotated[str, Form()] = "auto",
    instructions: Annotated[str, Form(max_length=20000)] = "",
    auto_process: Annotated[bool, Form()] = False,
    filename: Annotated[str, Form(max_length=1000)] = "",
):
    upload = find(db, UploadSession, id)
    if kind not in ("auto", "card", "brochure", "other"):
        raise HTTPException(422, "Choose card, brochure or other.")
    asset, doc, duplicate = await receive_file(
        db,
        upload,
        file,
        sha256,
        client_uuid,
        kind,
        request.app.state.settings,
        request.app.state.storage,
        {"instructions": instructions, "auto_process": auto_process, "auto_crop": True},
        filename,
    )
    return {
        "status": "saved",
        "asset": record(asset),
        "document": record(doc),
        "already_uploaded": duplicate,
    }


@router.post("/upload-sessions/{id}/complete")
def complete_session(id: UUID, session: OwnerSession, db: DB):
    upload = find(db, UploadSession, id)
    upload.state = "complete"
    db.commit()
    return record(upload)


@router.get("/assets/{id}/original")
def original(id: UUID, request: Request, session: OwnerSession, db: DB):
    request.app.state.storage.require_ready()
    asset = find(db, Asset, id)
    if asset.purged_at:
        raise HTTPException(410, "This original was permanently removed.")
    path = asset_path(request.app.state.settings.assets_dir, asset.storage_path)
    if not path.is_file():
        raise HTTPException(503, "This original is unavailable. Check the originals drive.")
    return FileResponse(
        path,
        media_type=asset.mime,
        filename=asset.original_filename,
        content_disposition_type="attachment",
        headers={"X-Content-Type-Options": "nosniff"},
    )
