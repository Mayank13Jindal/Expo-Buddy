from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.dependencies import DB, OwnerSession
from app.api.library import ExpoInput, find, record
from app.db.capture import CaptureGroup, CaptureItem, QueueReport, SyncReceipt
from app.db.library import Asset, Document, DocumentPage, Expo, Preference
from app.domain import capture

router = APIRouter(prefix="/api/v1/sync", tags=["phone sync"])


@router.post("/expos")
def sync_expo(body: ExpoInput, session: OwnerSession, db: DB):
    if not body.client_uuid:
        raise HTTPException(422, "A capture ID is required.")
    capture.lock_uuid(db, body.client_uuid)
    row = db.scalar(select(Expo).where(Expo.client_uuid == body.client_uuid))
    if not row:
        row = Expo(**body.model_dump())
        db.add(row)
        db.flush()
        db.add(SyncReceipt(client_uuid=body.client_uuid, kind="expo", server_id=row.id))
        preference = db.scalar(select(Preference).where(Preference.owner_id == session.owner_id))
        if not preference.active_expo_id:
            preference.active_expo_id = row.id
            preference.revision += 1
    db.commit()
    return {"status": "saved", **record(row)}


class GroupInput(BaseModel):
    client_uuid: UUID
    expo_id: UUID
    label: str = Field(default="", max_length=200)
    captured_at: datetime
    device_label: str = Field(default="Phone", max_length=100)


@router.post("/groups")
def sync_group(body: GroupInput, session: OwnerSession, db: DB):
    find(db, Expo, body.expo_id)
    capture.lock_uuid(db, body.client_uuid)
    row = db.scalar(select(CaptureGroup).where(CaptureGroup.client_uuid == body.client_uuid))
    if row and row.expo_id != body.expo_id:
        raise HTTPException(409, "This booth already belongs to another expo.")
    if not row:
        row = CaptureGroup(**body.model_dump())
        db.add(row)
        db.flush()
        db.add(SyncReceipt(client_uuid=body.client_uuid, kind="group", server_id=row.id))
    db.commit()
    return {"status": "saved", **record(row)}


class FileReceipt(BaseModel):
    client_uuid: UUID
    document_id: UUID
    asset_id: UUID
    sha256: str = Field(pattern="^[a-f0-9]{64}$")
    expo_id: UUID
    capture_group_id: UUID | None = None


@router.post("/files")
def file_receipt(body: FileReceipt, session: OwnerSession, db: DB):
    capture.lock_uuid(db, body.client_uuid)
    existing = db.scalar(select(CaptureItem).where(CaptureItem.client_uuid == body.client_uuid))
    if existing:
        if (
            existing.sha256 != body.sha256
            or existing.expo_id != body.expo_id
            or existing.capture_group_id != body.capture_group_id
        ):
            raise HTTPException(
                409, "This photo capture ID is already used. Keep its original expo."
            )
        return {"status": "saved", "id": existing.id}
    doc, asset = find(db, Document, body.document_id), find(db, Asset, body.asset_id)
    page = db.scalar(
        select(DocumentPage)
        .where(DocumentPage.document_id == doc.id, DocumentPage.asset_id == asset.id)
        .order_by(DocumentPage.order)
    )
    if doc.expo_id != body.expo_id or asset.sha256 != body.sha256 or not page:
        raise HTTPException(409, "The saved photo does not match this capture.")
    if body.capture_group_id:
        group = find(db, CaptureGroup, body.capture_group_id)
        if group.expo_id != doc.expo_id:
            raise HTTPException(409, "A booth must stay in its captured expo.")
        if not asset.capture_group_id:
            asset.capture_group_id = group.id
    row = CaptureItem(
        client_uuid=body.client_uuid,
        document_page_id=page.id,
        expo_id=doc.expo_id,
        sha256=asset.sha256,
        capture_group_id=body.capture_group_id,
    )
    db.add(row)
    db.flush()
    db.add(SyncReceipt(client_uuid=body.client_uuid, kind="file", server_id=row.id))
    from app.domain.tags import index_tags

    index_tags(db, doc)
    db.commit()
    return {"status": "saved", "id": row.id}


class NoteSync(BaseModel):
    client_uuid: UUID
    revision: int = Field(default=1, ge=1)
    target_kind: str = Field(pattern="^(file|group|expo)$")
    target_id: UUID
    text_value: str = Field(max_length=20000)
    deleted: bool = False


@router.post("/notes")
def sync_note(body: NoteSync, session: OwnerSession, db: DB):
    row = capture.save_note(db, **body.model_dump())
    db.commit()
    return {"status": "saved", "id": row.id, "revision": body.revision}


class TagSync(BaseModel):
    client_uuid: UUID
    target_kind: str = Field(pattern="^(file|group|expo)$")
    target_id: UUID
    labels: list[str] = Field(max_length=50)


@router.post("/tags")
def sync_tags(body: TagSync, session: OwnerSession, db: DB):
    row = capture.save_tags(db, **body.model_dump())
    db.commit()
    return {"status": "saved", "id": row.id}


class Report(BaseModel):
    client_uuid: UUID
    device_label: str = Field(max_length=100)
    files: int = Field(ge=0, le=100000)
    notes: int = Field(ge=0, le=100000)
    bytes: int = Field(ge=0)


@router.post("/report")
def queue_report(body: Report, session: OwnerSession, db: DB):
    capture.lock_uuid(db, body.client_uuid)
    row = db.scalar(select(QueueReport).where(QueueReport.client_uuid == body.client_uuid))
    if not row:
        row = QueueReport(**body.model_dump())
        db.add(row)
    else:
        for key, value in body.model_dump().items():
            setattr(row, key, value)
        from app.db.library import now

        row.updated_at = now()
    db.commit()
    return {"saved": True}


@router.delete("/report/{id}")
def dismiss_queue_report(id: UUID, session: OwnerSession, db: DB):
    from app.api.library import find

    db.delete(find(db, QueueReport, id))
    db.commit()
    return {"saved": True}
