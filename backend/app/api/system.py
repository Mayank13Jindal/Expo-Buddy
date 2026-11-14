from dataclasses import asdict

from fastapi import APIRouter, Request
from sqlalchemy import func, select

from app.api.dependencies import DB, OwnerSession
from app.api.health import read_health
from app.db.processing import Job
from app.pipeline.embeddings import MODELS

router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/status")
def status(request: Request, session: OwnerSession, db: DB):
    settings = request.app.state.settings
    health = read_health(request.app.state.engine, request.app.state.storage, settings)
    health["storage"] = [asdict(row) for row in request.app.state.storage.check()]
    health["jobs"] = dict(db.execute(select(Job.state, func.count()).group_by(Job.state)).all())
    health["models"] = [
        {
            "name": name,
            "cached": (settings.models_dir / "embeddings" / model[0] / "config.json").is_file(),
        }
        for name, model in MODELS.items()
    ]
    from app.pipeline.ocr import DETECTION, RECOGNITION

    health["models"] += [
        {
            "name": name,
            "cached": (settings.models_dir / "ocr" / name / "inference.pdiparams").is_file(),
        }
        for name in (DETECTION, RECOGNITION)
    ]
    health["errors"] = [
        {"stage": row.kind, "reason": row.error, "time": row.updated_at}
        for row in db.scalars(
            select(Job)
            .where(Job.state.in_(("failed", "waiting")), Job.error.is_not(None))
            .order_by(Job.updated_at.desc())
            .limit(10)
        )
    ]
    from app.domain.backups import status as backup_status

    health["backup"] = backup_status(db)
    try:
        health["backup"]["same_filesystem_as_originals"] = (
            settings.backup_dir.stat().st_dev == settings.assets_dir.stat().st_dev
        )
    except OSError:
        health["backup"]["same_filesystem_as_originals"] = None
    health["timezone"] = settings.app_timezone
    health["limits"] = {
        "image": settings.image_limit_bytes,
        "pdf": settings.pdf_limit_bytes,
        "pages": settings.pdf_page_limit,
    }
    return health
