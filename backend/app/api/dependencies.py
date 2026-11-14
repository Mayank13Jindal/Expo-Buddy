import hmac
from collections.abc import Generator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from app.core.security import digest
from app.db.library import Session


def get_db(request: Request) -> Generator[DatabaseSession]:
    with DatabaseSession(request.app.state.engine, expire_on_commit=False) as db:
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            db.info["library_write"] = True
        try:
            yield db
        except BaseException:
            db.rollback()
            raise


DB = Annotated[DatabaseSession, Depends(get_db, scope="function")]


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def same_origin(request: Request) -> None:
    if request.headers.get("origin") != request.app.state.settings.canonical_origin:
        raise HTTPException(403, "Open this app from its saved address and try again.")


def require_session(request: Request, db: DB) -> Session:
    token = request.cookies.get("expo_session", "")
    session = (
        db.scalar(select(Session).where(Session.token_hash == digest(token))) if token else None
    )
    if not session or aware(session.expires_at) <= datetime.now(UTC):
        raise HTTPException(401, "Please sign in.")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        same_origin(request)
        csrf = request.headers.get("x-csrf-token", "")
        if not csrf or not hmac.compare_digest(digest(csrf), session.csrf_hash):
            raise HTTPException(403, "Reload the page and try again.")
    # Release auth reads before another thread schedules the endpoint during request bursts.
    db.close()
    return session


OwnerSession = Annotated[Session, Depends(require_session)]
