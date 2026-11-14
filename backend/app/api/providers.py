from decimal import Decimal
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, HttpUrl, SecretStr

from app.api.dependencies import DB, OwnerSession
from app.core.secrets import cipher
from app.db.library import Owner
from app.domain import providers
from app.providers.base import ProviderFailure
from app.providers.schema import Extraction

router = APIRouter(prefix="/api/v1/settings/providers", tags=["providers"])


def public(row, settings=None):
    accounts = {}
    if row.provider == "chatgpt" and settings:
        from app.providers.chatgpt import account_store

        accounts = account_store(row, settings)
    state = row.last_status if row.enabled else "off"
    if row.provider == "chatgpt" and row.enabled and not accounts.get("accounts", {}).get(accounts.get("active"), {}).get("access_token"):
        state = "sign_in_required"
    return {
        "provider": row.provider,
        "enabled": row.enabled,
        "order": row.order,
        "model": row.model,
        "base_url": row.config.get("base_url", ""),
        "remote": row.config.get("remote", False),
        "has_secret": bool(row.encrypted_secret),
        "cooldown_until": row.cooldown_until,
        "state": state,
        "spent": str(row.spent),
        "reserved": str(row.reserved),
        "spending_cap": str(row.spending_cap),
        "usage_is_estimate": True,
        "timeout_seconds": row.config.get("timeout_seconds", 600),
        "pinned_digest": row.config.get("pinned_digest", ""),
        "active_account": accounts.get("active"),
        "accounts": [
            {
                "id": key,
                "label": value.get("email", "ChatGPT account"),
                "connected": bool(value.get("access_token")),
                "plan_enabled": "chatgpt.tokens.use.direct" in value.get("scopes", []),
            }
            for key, value in accounts.get("accounts", {}).items()
        ],
    }


@router.get("")
def get_providers(request: Request, session: OwnerSession, db: DB):
    rows = providers.ensure_providers(db)
    db.commit()
    owner = db.get(Owner, session.owner_id)
    return {
        "providers": [public(row, request.app.state.settings) for row in rows],
        "cloud_fallback": owner.settings.get("cloud_fallback", False),
        "chatgpt_block": "",
    }


class ProviderInput(BaseModel):
    provider: str = Field(pattern="^(ollama|chatgpt|openrouter)$")
    enabled: bool
    model: str = Field(default="", max_length=200)
    base_url: HttpUrl | None = None
    secret: SecretStr | None = None
    clear_secret: bool = False
    spending_cap: Decimal = Field(default=0, ge=0, le=100000)
    timeout_seconds: int = Field(default=600, ge=30, le=1800)
    pinned_digest: str | None = Field(default=None, max_length=100)


class SettingsInput(BaseModel):
    providers: list[ProviderInput] = Field(max_length=3)
    cloud_fallback: bool = False


@router.put("")
def save_providers(body: SettingsInput, request: Request, session: OwnerSession, db: DB):
    rows = {row.provider: row for row in providers.ensure_providers(db)}
    for entry in body.providers:
        row = rows[entry.provider]
        if entry.base_url and (entry.base_url.username or entry.base_url.password):
            raise HTTPException(422, "Enter an address without a username or password.")
        old_model = row.model
        row.enabled, row.model, row.spending_cap = (
            entry.enabled,
            entry.model.strip(),
            entry.spending_cap,
        )
        row.config = {
            **row.config,
            "base_url": str(entry.base_url).rstrip("/") if entry.base_url else "",
            "timeout_seconds": entry.timeout_seconds,
            "pinned_digest": entry.pinned_digest
            if entry.pinned_digest is not None
            else (row.config.get("pinned_digest", "") if old_model == row.model else ""),
        }
        if entry.secret and entry.secret.get_secret_value():
            row.encrypted_secret = (
                cipher(request.app.state.settings)
                .encrypt(entry.secret.get_secret_value().encode())
                .decode()
            )
        if entry.clear_secret:
            row.encrypted_secret = None
        row.cooldown_until, row.failures = None, 0
    owner = db.get(Owner, session.owner_id)
    owner.settings = {**owner.settings, "cloud_fallback": body.cloud_fallback}
    db.commit()
    return {"saved": True}


@router.post("/{name}/test")
def test_provider(name: str, request: Request, session: OwnerSession, db: DB):
    row = next((row for row in providers.ensure_providers(db) if row.provider == name), None)
    if not row:
        raise HTTPException(404, "This provider was not found.")
    if name == "ollama" and row.config.get("base_url"):
        try:
            response = httpx.get(row.config["base_url"] + "/api/tags", timeout=10)
            response.raise_for_status()
            model = next(
                (
                    model
                    for model in response.json().get("models", [])
                    if model["name"] == row.model
                ),
                None,
            )
            if not model:
                raise HTTPException(422, "That model is not installed in Ollama.")
            if row.config.get("pinned_digest") and row.config["pinned_digest"] != model.get(
                "digest"
            ):
                raise HTTPException(
                    409,
                    "The pinned model changed. Load the model list, review the new version and save it before testing.",
                )
            row.config = {
                **row.config,
                "model_digest": model.get("digest", ""),
                "remote": bool(
                    model.get("remote_model") or model.get("remote_host") or ":cloud" in row.model
                ),
            }
        except (httpx.HTTPError, ValueError, KeyError):
            raise HTTPException(422, "Ollama could not be reached. Check its address.") from None
    owner = db.get(Owner, session.owner_id)
    if (name == "openrouter" or row.config.get("remote")) and not owner.settings.get(
        "cloud_fallback"
    ):
        raise HTTPException(409, "Enable cloud processing before testing this provider.")
    try:
        if name == "chatgpt":
            from app.providers.chatgpt import connection

            connection(db, row, request.app.state.settings)
        provider = providers.adapter(row, request.app.state.settings)
        reply = providers.billed_call(
            db, row, provider, f"Document {uuid4()}\nPage {uuid4()}\nFICTIONAL SOLAR COMPANY\n"
        )
        Extraction.model_validate_json(reply.text)
        row.last_status = "online"
        row.cooldown_until = None
        db.commit()
        return {
            "connected": True,
            "inference_verified": True,
            "remote": row.config.get("remote", name == "openrouter"),
        }
    except (ProviderFailure, ValueError) as error:
        raise HTTPException(
            422,
            str(error)
            if isinstance(error, ProviderFailure)
            else "The provider's response needs checking.",
        ) from None
