import hmac
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import DB, OwnerSession, aware
from app.api.exports import MIMES
from app.api.library import find, record
from app.core.security import digest
from app.db.agent import AgentAudit, APIToken
from app.db.exports import Export
from app.db.library import now
from app.domain import agent
from app.domain.uploads import asset_path

router = APIRouter(prefix="/api/v1", tags=["agent access"])


def public(row):
    return {
        key: value
        for key, value in record(row).items()
        if key not in ("token_hash", "minute", "calls")
    }


class TokenInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(default=["read"], max_length=4)
    expires_at: datetime | None = None


@router.get("/settings/agent-tokens")
def tokens(session: OwnerSession, db: DB):
    return [
        public(row) for row in db.scalars(select(APIToken).order_by(APIToken.created_at.desc()))
    ]


@router.post("/settings/agent-tokens", status_code=201)
def issue(body: TokenInput, session: OwnerSession, db: DB):
    if body.expires_at and aware(body.expires_at) <= now():
        raise HTTPException(422, "Choose an expiry in the future.")
    row, secret = agent.issue(db, body.name, body.scopes, body.expires_at)
    db.commit()
    return {**public(row), "token": secret, "show_once": True}


@router.delete("/settings/agent-tokens/{id}")
def revoke(id: UUID, session: OwnerSession, db: DB):
    row = find(db, APIToken, id)
    row.revoked_at = now()
    db.commit()
    return {"revoked": True}


@router.get("/settings/agent-activity")
def activity(session: OwnerSession, db: DB):
    return [
        record(row)
        for row in db.scalars(select(AgentAudit).order_by(AgentAudit.created_at.desc()).limit(200))
    ]


def reserve_download_slot(engine, raw: str) -> tuple[UUID, float]:
    with Session(engine, expire_on_commit=False) as db:
        token, delay = agent.validate_queued(db, raw, rate_limit=True)
        db.commit()
        return token.id, delay


def prepare_download(engine, settings, token_id: UUID, id: UUID, ticket: str):
    with Session(engine, expire_on_commit=False) as db:
        token = db.get(APIToken, token_id)
        row = find(db, Export, id)
        agent.require_scope(token, "export")
        if (
            row.token_id != token.id
            or not row.download_hash
            or not row.download_until
            or aware(row.download_until) <= now()
            or not hmac.compare_digest(digest(ticket), row.download_hash)
        ):
            raise HTTPException(
                403, "This download ticket is missing, expired or belongs to a different token."
            )
        if row.state != "ready" or not row.expires_at or aware(row.expires_at) <= now():
            raise HTTPException(410, "Generate a fresh export.")
        path = asset_path(settings.exports_dir, row.path)
        if not path.is_file():
            raise HTTPException(410, "Generate a fresh export.")
        agent.audit(db, token.id, "download_export", {"id": id}, "succeeded")
        db.commit()
        return path, row.format, row.id


@router.get("/agent-download/{id}")
async def download(
    id: UUID, request: Request, authorization: str = Header(default=""), ticket: str = ""
):
    engine, settings = request.app.state.engine, request.app.state.settings
    raw = authorization[7:] if authorization.startswith("Bearer ") else ""
    token_id, delay = await run_in_threadpool(reserve_download_slot, engine, raw)
    if delay:
        # Over the per-minute limit: wait for this request's reserved slot instead of refusing it.
        await agent.wait_for_slot(delay)
    path, file_format, export_id = await run_in_threadpool(
        prepare_download, engine, settings, token_id, id, ticket
    )
    return FileResponse(
        path,
        media_type=MIMES[file_format],
        filename=f"Expo-Buddy-{str(export_id)[:8]}.{file_format}",
    )
