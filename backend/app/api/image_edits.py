from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from app.api.dependencies import DB, OwnerSession
from app.api.library import find, record
from app.db.library import Asset, Document, DocumentPage, now
from app.db.processing import AssetDerivative
from app.domain.jobs import enqueue

router = APIRouter(prefix="/api/v1/documents", tags=["source editing"])


class Rotation(BaseModel):
    page_id: UUID
    degrees: int = Field(default=90)


class Crop(BaseModel):
    page_id: UUID
    left: float = Field(ge=0, lt=1)
    top: float = Field(ge=0, lt=1)
    right: float = Field(gt=0, le=1)
    bottom: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def valid_box(self):
        if self.right <= self.left or self.bottom <= self.top:
            raise ValueError("Choose a crop with some width and height.")
        return self


def transform(db, id, page_id, operation):
    doc, page = find(db, Document, id), find(db, DocumentPage, page_id)
    if page.document_id != id:
        raise HTTPException(422, "Choose a page from this document.")
    previous = db.scalar(
        select(AssetDerivative)
        .where(AssetDerivative.document_page_id == page_id, AssetDerivative.kind == "transform")
        .order_by(AssetDerivative.revision.desc())
        .limit(1)
    )
    operations = list(previous.params.get("operations", [])) if previous else []
    base = previous.params.get("base_preparation") if previous else None
    if not previous or previous.params.get("auto_base_pending"):
        prepared = db.scalar(
            select(AssetDerivative).where(
                AssetDerivative.document_page_id == page_id,
                AssetDerivative.kind == "preview",
                AssetDerivative.revision == doc.revision,
            )
        )
        base = prepared.params.get("auto_crop") if prepared else None
    operations.append(operation)
    doc.revision += 1
    doc.processing_state = "received"
    db.add(
        AssetDerivative(
            asset_id=page.asset_id,
            document_page_id=page.id,
            kind="transform",
            revision=doc.revision,
            path="",
            params={"operations": operations, "base_preparation": base},
        )
    )
    enqueue(db, "prepare", doc.id, doc.revision)
    db.commit()
    return record(doc)


@router.post("/{id}/rotate")
def rotate(id: UUID, body: Rotation, session: OwnerSession, db: DB):
    if body.degrees not in (90, 180, 270):
        raise HTTPException(422, "Choose a quarter, half, or three-quarter turn.")
    return transform(db, id, body.page_id, {"kind": "rotate", "degrees": body.degrees})


@router.post("/{id}/crop")
def crop(id: UUID, body: Crop, session: OwnerSession, db: DB):
    return transform(db, id, body.page_id, {"kind": "crop", **body.model_dump(exclude={"page_id"})})


class Replace(BaseModel):
    page_id: UUID
    asset_id: UUID
    replacement_document_id: UUID | None = None


@router.post("/{id}/replace")
def replace(id: UUID, body: Replace, session: OwnerSession, db: DB):
    doc, page, asset = (
        find(db, Document, id),
        find(db, DocumentPage, body.page_id),
        find(db, Asset, body.asset_id),
    )
    if page.document_id != id or asset.page_count != 1 or not asset.mime.startswith("image/"):
        raise HTTPException(422, "Replace one page with a photo.")
    old_asset = page.asset_id
    page.asset_id, page.pdf_page_no = asset.id, None
    doc.revision += 1
    doc.processing_state = "received"
    doc.processing_options = {**doc.processing_options, "auto_crop": True}
    db.add(
        AssetDerivative(
            asset_id=old_asset,
            document_page_id=page.id,
            kind="replacement",
            revision=doc.revision,
            path="",
            params={"old_asset_id": str(old_asset), "new_asset_id": str(asset.id)},
        )
    )
    db.add(
        AssetDerivative(
            asset_id=asset.id,
            document_page_id=page.id,
            kind="transform",
            revision=doc.revision,
            path="",
            params={"operations": [], "auto_base_pending": True},
        )
    )
    if body.replacement_document_id and body.replacement_document_id != doc.id:
        received = find(db, Document, body.replacement_document_id)
        linked = db.scalar(
            select(DocumentPage.id).where(
                DocumentPage.document_id == received.id, DocumentPage.asset_id == asset.id
            )
        )
        if not linked or received.expo_id != doc.expo_id:
            raise HTTPException(422, "The new photo must be uploaded for this expo.")
        received.deleted_at = now()
    enqueue(db, "prepare", doc.id, doc.revision)
    db.commit()
    return record(doc)


@router.get("/{id}/versions")
def versions(id: UUID, session: OwnerSession, db: DB):
    find(db, Document, id)
    return [
        record(row)
        for row in db.scalars(
            select(AssetDerivative)
            .join(DocumentPage)
            .where(
                DocumentPage.document_id == id,
                AssetDerivative.kind.in_(("replacement", "transform")),
            )
            .order_by(AssetDerivative.created_at.desc())
        )
    ]
