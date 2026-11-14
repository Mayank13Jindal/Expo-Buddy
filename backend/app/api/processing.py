import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import DB, OwnerSession, aware
from app.api.library import find, record
from app.db.library import Asset, Document, DocumentPage
from app.db.library import Session as OwnerSessionModel
from app.db.operations import Backup
from app.db.processing import AssetDerivative, ExtractionRun, Job, OCRResult
from app.domain.jobs import enqueue
from app.domain.uploads import asset_path

router = APIRouter(prefix="/api/v1", tags=["processing"])


@router.get("/assets/{id}/{kind}")
def derivative(
    id: UUID,
    kind: str,
    request: Request,
    session: OwnerSession,
    db: DB,
    page_id: UUID | None = None,
    revision: int | None = None,
):
    if kind not in ("thumbnail", "preview"):
        raise HTTPException(404, "This preview was not found.")
    find(db, Asset, id)
    statement = select(AssetDerivative).where(
        AssetDerivative.asset_id == id, AssetDerivative.kind == kind
    )
    if page_id:
        statement = statement.where(AssetDerivative.document_page_id == page_id)
    if revision is not None:
        statement = statement.where(AssetDerivative.revision == revision)
    item = db.scalar(statement.order_by(AssetDerivative.created_at.desc()).limit(1))
    if not item:
        raise HTTPException(404, "A preview is being prepared.")
    path = asset_path(request.app.state.settings.previews_dir, item.path)
    if not path.is_file():
        raise HTTPException(404, "This preview needs to be rebuilt.")
    return FileResponse(path, media_type="image/webp")


@router.get("/documents/{id}/text")
def document_text(id: UUID, session: OwnerSession, db: DB):
    find(db, Document, id)
    results = db.execute(
        select(DocumentPage, OCRResult)
        .join(OCRResult, OCRResult.document_page_id == DocumentPage.id)
        .where(DocumentPage.document_id == id)
        .order_by(DocumentPage.order, OCRResult.revision.desc())
    )
    pages, seen = [], set()
    for page, ocr in results:
        if page.id not in seen:
            pages.append(
                {
                    "page_id": page.id,
                    "order": page.order,
                    "text": ocr.text,
                    "engine": ocr.engine_version,
                    "revision": ocr.revision,
                    "lines": ocr.raw.get("lines", []),
                }
            )
            seen.add(page.id)
    return {"pages": pages}


class ReprocessInput(BaseModel):
    instructions: str = Field(default="", max_length=20000)
    image_check: bool = False
    auto_crop: bool = True


@router.post("/documents/{id}/reprocess")
def reprocess(id: UUID, session: OwnerSession, db: DB, body: ReprocessInput | None = None):
    body = body or ReprocessInput()
    doc = find(db, Document, id)
    if doc.deleted_at:
        raise HTTPException(409, "Restore this document before processing it.")
    doc.processing_options = {
        **doc.processing_options,
        **body.model_dump(exclude_unset=True),
        "auto_process": True,
    }
    doc.group_state = "confirmed"
    doc.revision += 1
    doc.processing_state = "received"
    enqueue(db, "prepare", doc.id, doc.revision)
    db.commit()
    return record(doc)


@router.get("/documents/{id}/progress")
def progress(id: UUID, session: OwnerSession, db: DB):
    doc = find(db, Document, id)
    rows = list(
        db.scalars(
            select(Job)
            .where(Job.target_id == id, Job.input_revision == doc.revision)
            .order_by(Job.created_at)
        )
    )
    runs = list(
        db.scalars(
            select(ExtractionRun).where(
                ExtractionRun.document_id == id, ExtractionRun.input_revision == doc.revision
            )
        )
    )

    def step(row):
        failures = [run for run in runs if run.stage == row.kind and run.status == "needs_review"]
        if failures:
            return {"step": row.kind, "state": "needs_review", "reason": failures[-1].error}
        if row.kind == "ai" and doc.processing_state == "needs_review":
            return {"step": "ai", "state": "needs_review", "reason": "No readable text to extract."}
        return {"step": row.kind, "state": row.state, "reason": row.error}

    return {
        "state": doc.processing_state,
        "steps": [step(row) for row in rows if row.kind in ("prepare", "read", "ai", "vision")],
        "review_reasons": doc.review_reasons,
    }


@router.get("/search")
def search(
    request: Request,
    session: OwnerSession,
    db: DB,
    q: str = Query(min_length=1, max_length=500),
    expo_id: UUID | None = None,
    scope: str = "active",
    limit: int = 50,
    type: str | None = None,
    review_state: str | None = None,
    company_id: UUID | None = None,
    tag: str | None = None,
    category: str | None = None,
    processed_by: str | None = None,
    include_related: bool = False,
):
    from app.db.library import Preference
    from app.domain.hybrid import hybrid_search

    if scope != "all" and expo_id is None:
        preference = db.scalar(select(Preference).where(Preference.owner_id == session.owner_id))
        expo_id = preference.active_expo_id if preference else None
    if not q.strip():
        return {"query": q, "results": [], "semantic_available": False}
    return hybrid_search(
        db,
        request.app.state.settings,
        q.strip(),
        include_related=include_related,
        expo_id=expo_id,
        limit=limit,
        type=type,
        review_state=review_state,
        company_id=company_id,
        tag=tag,
        category=category,
        processed_by=processed_by,
    )


@router.get("/jobs")
def jobs(session: OwnerSession, db: DB):
    return [
        record(job) for job in db.scalars(select(Job).order_by(Job.created_at.desc()).limit(100))
    ]


@router.get("/events")
def events(request: Request, session: OwnerSession, db: DB):
    session_id = session.id
    engine = request.app.state.engine
    db.close()

    def snapshot():
        with Session(engine) as connection:
            login = connection.get(OwnerSessionModel, session_id)
            if not login or aware(login.expires_at) <= datetime.now(UTC):
                return None
            rows = connection.execute(select(Job.state, func.count()).group_by(Job.state)).all()
            documents = connection.execute(
                select(func.count(Document.id), func.max(Document.updated_at))
            ).first()
            from app.db.capture import QueueReport
            from app.db.intelligence import EditHistory, ProviderSetting
            from app.db.library import Note, Preference

            updates = {
                model.__tablename__: connection.scalar(select(func.max(model.updated_at)))
                for model in (QueueReport, EditHistory, ProviderSetting, Note, Preference, Backup)
            }
            data = json.dumps(
                jsonable_encoder(
                    {"jobs": dict(rows), "documents": list(documents), "updates": updates}
                )
            )
        return data

    async def stream():
        previous = None
        while not await request.is_disconnected():
            data = await run_in_threadpool(snapshot)
            if data is None:
                break
            if data != previous:
                yield f"event: progress\ndata: {data}\n\n"
                previous = data
            else:
                yield ": keep-alive\n\n"
            await asyncio.sleep(3)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
