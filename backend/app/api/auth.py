from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import DB, OwnerSession, aware, same_origin
from app.core.security import check_password, digest, hasher, random_token
from app.db.library import Owner, Preference, Session

router = APIRouter(prefix="/api/v1/auth", tags=["account"])


class Credentials(BaseModel):
    password: SecretStr = Field(min_length=8, max_length=256)


def sign_in(owner: Owner, request: Request, response: Response, db: DB) -> dict:
    token, csrf = random_token(), random_token()
    days = request.app.state.settings.session_days
    db.add(
        Session(
            owner_id=owner.id,
            token_hash=digest(token),
            csrf_hash=digest(csrf),
            expires_at=datetime.now(UTC) + timedelta(days=days),
            user_agent=request.headers.get("user-agent", "")[:256],
        )
    )
    db.commit()
    response.set_cookie(
        "expo_session", token, max_age=days * 86400, secure=True, httponly=True, samesite="lax"
    )
    response.set_cookie(
        "expo_csrf", csrf, max_age=days * 86400, secure=True, httponly=False, samesite="lax"
    )
    return {"signed_in": True}


@router.get("/status")
def account_status(request: Request, db: DB) -> dict:
    return {"setup_required": db.scalar(select(Owner.id)) is None, "password_required": not request.app.state.settings.passwordless}


@router.post("/setup", status_code=201)
def setup(body: Credentials, request: Request, response: Response, db: DB):
    same_origin(request)
    if db.scalar(select(Owner.id)):
        raise HTTPException(409, "An account already exists. Please sign in.")
    owner = Owner(password_hash=hasher.hash(body.password.get_secret_value()))
    db.add(owner)
    try:
        db.flush()
        db.add(Preference(owner_id=owner.id))
        from app.domain.providers import ensure_providers

        ensure_providers(db)
        return sign_in(owner, request, response, db)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An account already exists. Please sign in.") from None


@router.post("/open")
def open_library(request: Request, response: Response, db: DB):
    same_origin(request)
    if not request.app.state.settings.passwordless:
        raise HTTPException(403, "Password-free access is disabled.")
    owner = db.scalar(select(Owner).with_for_update())
    if owner is None:
        owner = Owner(password_hash=hasher.hash(random_token()))
        db.add(owner)
        db.flush()
        db.add(Preference(owner_id=owner.id))
        from app.domain.providers import ensure_providers

        ensure_providers(db)
    return sign_in(owner, request, response, db)


@router.post("/login")
def login(body: Credentials, request: Request, response: Response, db: DB):
    same_origin(request)
    owner = db.scalar(select(Owner).with_for_update())
    if not owner:
        raise HTTPException(401, "Create your account first.")
    if owner.locked_until and aware(owner.locked_until) > datetime.now(UTC):
        raise HTTPException(429, "Too many attempts. Wait a few minutes before trying again.")
    if not check_password(body.password.get_secret_value(), owner.password_hash):
        owner.failed_logins += 1
        if owner.failed_logins % 10 == 0:
            # Each further 10 failures doubles the lock (1, 2, 4 ... minutes, capped at a day).
            minutes = min(2 ** (owner.failed_logins // 10 - 1), 1440)
            owner.locked_until = datetime.now(UTC) + timedelta(minutes=minutes)
        db.commit()
        raise HTTPException(401, "The password is incorrect.")
    owner.failed_logins = 0
    owner.locked_until = None
    return sign_in(owner, request, response, db)


@router.get("/me")
def me(request: Request, session: OwnerSession) -> dict:
    return {"signed_in": True, "owner_id": session.owner_id, "password_required": not request.app.state.settings.passwordless}


@router.post("/logout")
def logout(session: OwnerSession, response: Response, db: DB) -> dict:
    db.delete(session)
    db.commit()
    response.delete_cookie("expo_session", secure=True, httponly=True, samesite="lax")
    response.delete_cookie("expo_csrf", secure=True, samesite="lax")
    return {"signed_in": False}


class PasswordChange(Credentials):
    current_password: SecretStr = Field(max_length=256)


@router.post("/password")
def change_password(body: PasswordChange, session: OwnerSession, db: DB):
    owner = db.get(Owner, session.owner_id)
    if not check_password(body.current_password.get_secret_value(), owner.password_hash):
        raise HTTPException(403, "The current password is incorrect.")
    owner.password_hash = hasher.hash(body.password.get_secret_value())
    db.execute(delete(Session).where(Session.id != session.id))
    db.commit()
    return {"saved": True}
