from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.dependencies import DB, OwnerSession
from app.api.library import record
from app.db.library import Owner
from app.db.operations import Backup
from app.domain import backups

router = APIRouter(prefix="/api/v1/system", tags=["operations"])


class BackupConfig(BaseModel):
    enabled: bool = True
    hour: int = Field(default=2, ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    daily_keep: int = Field(default=7, ge=1, le=90)
    weekly_keep: int = Field(default=4, ge=1, le=52)


@router.get("/backup-settings")
def backup_settings(session: OwnerSession, db: DB):
    return backups.configuration(db)


@router.put("/backup-settings")
def save_backup_settings(body: BackupConfig, session: OwnerSession, db: DB):
    owner = db.get(Owner, session.owner_id)
    owner.settings = {**owner.settings, "backup": body.model_dump()}
    db.commit()
    return backups.configuration(db)


@router.get("/backups")
def list_backups(session: OwnerSession, db: DB):
    return [
        record(row)
        for row in db.scalars(select(Backup).order_by(Backup.created_at.desc()).limit(100))
    ]


@router.post("/backup", status_code=202)
def start_backup(request: Request, session: OwnerSession, db: DB):
    request.app.state.storage.require_ready()
    row = backups.queue(db)
    db.commit()
    return record(row)
