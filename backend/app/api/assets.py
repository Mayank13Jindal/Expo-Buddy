from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import select

from app.api.dependencies import DB, OwnerSession
from app.api.library import find, record
from app.db.library import Asset, DocumentPage
from app.db.processing import OCRResult

router = APIRouter(prefix="/api/v1", tags=["sources"])


@router.get("/assets/{id}")
def asset_metadata(id: UUID, session: OwnerSession, db: DB):
    return record(find(db, Asset, id))


@router.get("/pages/{id}/location")
def page_location(id: UUID, session: OwnerSession, db: DB, quote: str = ""):
    row = find(db, DocumentPage, id)
    result = {"document_id": row.document_id, "page_id": row.id, "order": row.order}
    if quote and len(quote) <= 1000:

        def normal(value):
            return " ".join(value.casefold().split())

        for ocr in db.scalars(
            select(OCRResult)
            .where(OCRResult.document_page_id == id)
            .order_by(OCRResult.revision.desc())
        ):
            if normal(quote) in normal(ocr.text):
                result.update(
                    asset_id=ocr.raw.get("asset_id", str(row.asset_id)), revision=ocr.revision
                )
                line = next(
                    (
                        line
                        for line in ocr.raw.get("lines", [])
                        if normal(line["text"]) in normal(quote)
                        or normal(quote) in normal(line["text"])
                    ),
                    None,
                )
                if line and ocr.raw.get("image_width") and ocr.raw.get("image_height"):
                    result["box"] = [
                        [
                            point[0] / ocr.raw["image_width"] * 100,
                            point[1] / ocr.raw["image_height"] * 100,
                        ]
                        for point in line["box"]
                    ]
                break
    return result
