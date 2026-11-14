from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.dependencies import DB, OwnerSession, aware
from app.api.library import find, record
from app.db.exports import Export, ExportPreset
from app.db.library import Preference, now
from app.domain import exports
from app.domain.uploads import asset_path
from app.exports.schema import FIELDS, Selection

router = APIRouter(prefix="/api/v1", tags=["exports"])
MIMES = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv; charset=utf-8",
    "vcf": "text/vcard; charset=utf-8",
    "zip": "application/zip",
}


def public(row):
    return {
        key: value
        for key, value in record(row).items()
        if key not in ("snapshot", "download_hash", "path", "token_id")
    }


def active_expo(db, owner_id):
    return db.scalar(select(Preference.active_expo_id).where(Preference.owner_id == owner_id))


@router.get("/export-fields")
def export_fields(session: OwnerSession):
    return FIELDS


@router.post("/exports/preview")
def preview(body: Selection, request: Request, session: OwnerSession, db: DB):
    snapshot = exports.freeze(
        db, body, request.app.state.settings, active_expo(db, session.owner_id)
    )
    return {
        "counts": snapshot["counts"],
        "rows": {
            table: [
                {key: value for key, value in row.items() if not key.startswith("_")}
                for row in rows[:5]
            ]
            for table, rows in snapshot["tables"].items()
        },
        "fields": body.fields,
        "warning": "Original photos, PDFs and brochure text still contain printed information. Deselecting fields is not redaction.",
    }


@router.post("/exports", status_code=202)
def create_export(body: Selection, request: Request, session: OwnerSession, db: DB):
    request.app.state.storage.require_ready()
    row = exports.create(db, body, request.app.state.settings, active_expo(db, session.owner_id))
    db.commit()
    return public(row)


@router.get("/exports")
def list_exports(session: OwnerSession, db: DB):
    return [
        public(row)
        for row in db.scalars(
            select(Export)
            .where(Export.token_id.is_(None))
            .order_by(Export.created_at.desc())
            .limit(100)
        )
    ]


@router.get("/exports/{id}")
def get_export(id: UUID, session: OwnerSession, db: DB):
    return public(find(db, Export, id))


@router.get("/exports/{id}/download")
def download(id: UUID, request: Request, session: OwnerSession, db: DB):
    row = find(db, Export, id)
    if row.state != "ready" or not row.expires_at or aware(row.expires_at) <= now():
        raise HTTPException(410, "This export is not available. Generate a fresh copy.")
    path = asset_path(request.app.state.settings.exports_dir, row.path)
    if not path.is_file():
        raise HTTPException(410, "This export file is missing. Generate a fresh copy.")
    return FileResponse(
        path, media_type=MIMES[row.format], filename=f"Expo-Buddy-{str(row.id)[:8]}.{row.format}"
    )


class PresetInput(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    selection: Selection


@router.get("/export-presets")
def presets(session: OwnerSession, db: DB):
    return [record(row) for row in db.scalars(select(ExportPreset).order_by(ExportPreset.name))]


@router.post("/export-presets", status_code=201)
def save_preset(body: PresetInput, session: OwnerSession, db: DB):
    # Presets retain format and fields, never a stale selection of somebody else's records.
    selection = body.selection.model_dump(mode="json")
    selection.update(
        allow_unreviewed=False,
        scope="active",
        expo_ids=[],
        document_ids=[],
        company_ids=[],
        query="",
        filters={},
    )
    row = ExportPreset(name=body.name, selection=selection)
    db.add(row)
    db.commit()
    return record(row)


@router.delete("/export-presets/{id}")
def remove_preset(id: UUID, session: OwnerSession, db: DB):
    db.delete(find(db, ExportPreset, id))
    db.commit()
    return {"saved": True}
