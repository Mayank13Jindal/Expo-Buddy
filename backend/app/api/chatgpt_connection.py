import base64
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.dependencies import DB, OwnerSession
from app.domain import providers
from app.providers import chatgpt
from app.providers.base import ProviderFailure
from app.providers.oauth_crypto import RESOURCE, unseal, validate_credentials

router = APIRouter(prefix="/api/v1/settings/providers", tags=["ChatGPT connection"])


def row_for(db, name):
    row = next((row for row in providers.ensure_providers(db) if row.provider == name), None)
    if not row:
        raise HTTPException(404, "Provider not found.")
    return row


def host_keys(settings):
    private = X25519PrivateKey.from_private_bytes(
        hashlib.sha256(
            base64.urlsafe_b64decode(settings.encryption_key_file.read_bytes().strip())
            + b"expo-siwc"
            + settings.host_id.bytes
        ).digest()
    )
    return private, "urn:uuid:" + str(settings.host_id)


@router.get("/chatgpt/helper")
def helper(request: Request, session: OwnerSession, db: DB, new_account: bool = False):
    settings = request.app.state.settings
    private, host_id = host_keys(settings)
    store = chatgpt.account_store(row_for(db, "chatgpt"), settings)
    selected = store["accounts"].get(store["active"], {}) if not new_account else {}
    profile = {
        "host_id": host_id,
        "public_key": private.public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        .hex(),
        "client_id": selected.get("client_id"),
    }
    output = io.BytesIO()
    folder = Path(__file__).parents[1] / "providers"
    with ZipFile(output, "w") as archive:
        for name in ("connect_helper.py", "oauth_crypto.py"):
            archive.write(folder / name, name)
        archive.writestr("expo-host.json", json.dumps(profile))
        archive.writestr("requirements.txt", "httpx==0.28.1\nPyJWT==2.15.1\ncryptography==50.0.2\n")
        archive.writestr(
            "README.txt",
            "Run on your PC with Python 3.12+:\npython -m venv .venv\nActivate that environment, then:\npython -m pip install -r requirements.txt\npython connect_helper.py\n\nSign in only on the OpenAI page. Import chatgpt-connection.expo in Expo Buddy Settings. No password or raw token is requested by Expo Buddy.\n",
        )
    return Response(
        output.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="expo-chatgpt-connect.zip"',
            "Cache-Control": "no-store",
        },
    )


class ConnectionFile(BaseModel):
    host_id: str = Field(max_length=100)
    ephemeral: str = Field(max_length=64)
    nonce: str = Field(max_length=24)
    payload: str = Field(max_length=100000)


@router.post("/chatgpt/import")
def import_connection(body: ConnectionFile, request: Request, session: OwnerSession, db: DB):
    settings = request.app.state.settings
    private, host_id = host_keys(settings)
    try:
        value = unseal(body.model_dump(), private, host_id)
        value = validate_credentials(value)
        if value["ext_agent_host_id"] != host_id:
            raise ValueError("Server identity mismatch.")
    except Exception:
        raise HTTPException(
            422,
            "This connection could not be verified. Use a fresh helper from this server and sign in again.",
        ) from None
    return save_connection(db, settings, value)


def save_connection(db, settings, value):
    row = row_for(db, "chatgpt")
    store = chatgpt.account_store(row, settings)
    fingerprint = hashlib.sha256(
        (value["access_token"] + value.get("refresh_token", "") + value["id_token"]).encode()
    ).hexdigest()
    for saved in store["accounts"].values():
        if saved["client_id"] == value["client_id"] and saved["subject"] != value["subject"]:
            raise HTTPException(
                409,
                "This registration belongs to a different account. Download the helper for a new account.",
            )
        if saved.get("import_fingerprint") == fingerprint:
            raise HTTPException(
                409,
                "This connection was already imported. Reconnect with a fresh sign-in rather than replaying an old refresh token.",
            )
    value["import_fingerprint"] = fingerprint
    key = hashlib.sha256(
        (value["issuer"] + value["subject"] + value["client_id"]).encode()
    ).hexdigest()[:24]
    if key not in store["accounts"] and len(store["accounts"]) >= 5:
        raise HTTPException(409, "Up to five account registrations can be saved.")
    store["accounts"][key], store["active"] = value, key
    chatgpt.save_store(row, settings, store)
    row.last_status = (
        "connected" if "chatgpt.tokens.use.direct" in value["scopes"] else "plan_permission_needed"
    )
    row.enabled = "chatgpt.tokens.use.direct" in value["scopes"]
    row.cooldown_until, row.failures = None, 0
    db.commit()
    return {
        "connected": True,
        "plan_enabled": "chatgpt.tokens.use.direct" in value["scopes"],
        "inference_verified": False,
    }


@router.post("/chatgpt/sign-in")
def start_sign_in(request: Request, session: OwnerSession, db: DB, new_account: bool = False):
    settings = request.app.state.settings
    flow = getattr(request.app.state, "chatgpt_loopback", None)
    if flow is None:
        from sqlalchemy.orm import Session as DatabaseSession

        from app.providers.loopback import LoopbackSignIn

        def save(value):
            with DatabaseSession(request.app.state.engine) as connection:
                save_connection(connection, settings, value)

        try:
            flow = LoopbackSignIn(
                settings.chatgpt_callback_port,
                "urn:uuid:" + str(settings.host_id),
                save,
                bind=settings.chatgpt_callback_bind,
            )
        except OSError:
            raise HTTPException(
                409, "The local sign-in port is in use. Use the PC helper instead."
            ) from None
        request.app.state.chatgpt_loopback = flow
    store = chatgpt.account_store(row_for(db, "chatgpt"), settings)
    account = {} if new_account else store["accounts"].get(store["active"], {})
    return flow.start(account)


@router.get("/chatgpt/sign-in")
def sign_in_status(request: Request, session: OwnerSession):
    flow = getattr(request.app.state, "chatgpt_loopback", None)
    return flow.status() if flow else {"state": "idle", "message": ""}


@router.delete("/chatgpt/sign-in")
def cancel_sign_in(request: Request, session: OwnerSession):
    flow = getattr(request.app.state, "chatgpt_loopback", None)
    if flow:
        flow.cancel()
    return {"state": "idle", "message": "Sign-in cancelled."}


class AccountChoice(BaseModel):
    account_id: str = Field(max_length=24)


@router.post("/chatgpt/account")
def choose_account(body: AccountChoice, request: Request, session: OwnerSession, db: DB):
    row = row_for(db, "chatgpt")
    store = chatgpt.account_store(row, request.app.state.settings)
    if body.account_id not in store["accounts"]:
        raise HTTPException(404, "Account not found.")
    store["active"] = body.account_id
    chatgpt.save_store(row, request.app.state.settings, store)
    row.last_status, row.cooldown_until = "connected", None
    db.commit()
    return {"saved": True}


@router.post("/chatgpt/disconnect")
def disconnect(request: Request, session: OwnerSession, db: DB):
    flow = getattr(request.app.state, "chatgpt_loopback", None)
    if flow:
        flow.cancel()
    row = row_for(db, "chatgpt")
    settings = request.app.state.settings
    store = chatgpt.account_store(row, settings)
    value = store["accounts"].get(store["active"], {})
    revoked = False
    if value.get("refresh_token"):
        try:
            with httpx.Client(timeout=20) as web:
                discovery = web.get("https://auth.openai.com/.well-known/openid-configuration")
                discovery.raise_for_status()
                endpoint = discovery.json()["revocation_endpoint"]
                if not endpoint.startswith("https://auth.openai.com/"):
                    raise ValueError("Unexpected issuer endpoint")
                revoked = (
                    web.post(
                        endpoint,
                        data={
                            "client_id": value["client_id"],
                            "token": value["refresh_token"],
                            "token_type_hint": "refresh_token",
                        },
                    ).status_code
                    == 200
                )
        except (httpx.HTTPError, ValueError, KeyError):
            pass
    for field in ("access_token", "refresh_token", "id_token", "nonce"):
        value.pop(field, None)
    chatgpt.save_store(row, settings, store)
    row.enabled, row.last_status = False, "signed_out"
    db.commit()
    return {"signed_out": True, "remote_revocation_confirmed": revoked}


@router.get("/{name}/models")
def models(name: str, request: Request, session: OwnerSession, db: DB):
    row, settings = row_for(db, name), request.app.state.settings
    try:
        with httpx.Client(timeout=20) as web:
            if name == "chatgpt":
                value = chatgpt.connection(db, row, settings)
                response = web.get(
                    RESOURCE + "/models",
                    headers={"Authorization": "Bearer " + value["access_token"]},
                )
                response.raise_for_status()
                return {
                    "models": [
                        {"id": item["slug"], "name": item.get("display_name", item["slug"])}
                        for item in response.json()["models"]
                        if item.get("visibility") == "list"
                    ]
                }
            if name == "ollama" and row.config.get("base_url"):
                response = web.get(row.config["base_url"] + "/api/tags")
                response.raise_for_status()
                return {
                    "models": [
                        {"id": item["name"], "name": item["name"], "digest": item.get("digest", "")}
                        for item in response.json().get("models", [])
                    ]
                }
    except ProviderFailure as error:
        raise HTTPException(422, str(error)) from None
    except (httpx.HTTPError, KeyError, ValueError):
        raise HTTPException(
            422, "Could not load models. Check the saved connection and sign-in permission."
        ) from None
    raise HTTPException(422, "Save an Ollama address first.")
