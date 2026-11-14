from datetime import UTC, datetime, timedelta
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import aware
from app.core.config import Settings
from app.core.secrets import cipher
from app.db.intelligence import ProviderSetting
from app.db.library import Owner
from app.domain.jobs import WaitForResource
from app.providers.base import ProviderFailure
from app.providers.chatgpt import ChatGPT
from app.providers.ollama import Ollama
from app.providers.openrouter import OpenRouter
from app.providers.schema import Extraction, coverage_issues


def decode_extraction(raw, text, *, require_complete=True):
    import json
    import re

    value = json.loads(raw)
    labels = dict(re.findall(r"Page (P\d+) \[([0-9a-f-]{36})\]", text))

    def visit(item):
        if isinstance(item, dict):
            if item.get("page_id") in labels:
                item["page_id"] = labels[item["page_id"]]
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    result = Extraction.model_validate(value)
    # Valid JSON can still omit clearly printed contact details. Repair once, never invent them.
    source = text.split("Owner context (not printed evidence):", 1)[0]
    emails = set(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", source))
    extracted = {item.raw.casefold() for item in result.channels if item.kind == "email"}
    extracted.update(
        item.raw.casefold()
        for person in result.people
        for item in person.channels
        if item.kind == "email"
    )
    if require_complete and emails and not extracted:
        raise ValueError("Printed email omitted; return all printed contact fields.")
    if require_complete and coverage_issues(result, source):
        raise ValueError("The extraction omitted clear printed fields.")
    if result.company_name is None:
        result.review_reasons = list(
            dict.fromkeys(
                result.review_reasons
                + [
                    "Company name missing: compare logo and email domain with the source; domain alone is not verified company evidence."
                ]
            )
        )
    return result


ORDER = ("ollama", "chatgpt", "openrouter")


class InvalidExtraction(Exception):
    def __init__(self, message, provider="", model=""):
        super().__init__(message)
        self.provider, self.model = provider, model


def ensure_providers(db: Session):
    rows = {row.provider: row for row in db.scalars(select(ProviderSetting))}
    for index, name in enumerate(ORDER):
        if name not in rows:
            row = ProviderSetting(provider=name, enabled=False, order=index + 1)
            db.add(row)
            db.flush()
            rows[name] = row
    return [rows[name] for name in ORDER]


def adapter(row: ProviderSetting, settings: Settings):
    if row.provider == "ollama":
        if not row.config.get("base_url") or not row.model:
            raise ProviderFailure("Ollama needs an address and model in Settings.", fallback=True)
        return Ollama(
            row.config["base_url"], row.model, timeout=row.config.get("timeout_seconds", settings.ollama_timeout_seconds)
        )
    if row.provider == "chatgpt":
        from app.providers.chatgpt import account_store

        store = account_store(row, settings)
        value = store["accounts"].get(store["active"], {})
        if not value.get("access_token") or not row.model:
            raise ProviderFailure("Connect ChatGPT and choose a model in Settings.", fallback=True)
        return ChatGPT(value["access_token"], row.model)
    if not row.encrypted_secret or not row.model:
        raise ProviderFailure("OpenRouter needs a key and model in Settings.", fallback=True)
    return OpenRouter(row.model, cipher(settings).decrypt(row.encrypted_secret.encode()).decode())


def billed_call(db: Session, row: ProviderSetting, provider, text: str, repair: str | None = None):
    reserved = Decimal(0)
    if row.provider == "openrouter":
        reserved = provider.maximum_cost(text, repair)
        current = db.scalar(
            select(ProviderSetting).where(ProviderSetting.id == row.id).with_for_update()
        )
        month = datetime.now(UTC).strftime("%Y-%m")
        if current.month != month:
            current.month, current.spent, current.reserved = month, Decimal(0), Decimal(0)
        if (
            not reserved.is_finite()
            or reserved < 0
            or current.spending_cap <= 0
            or current.spent + current.reserved + reserved > current.spending_cap
        ):
            raise ProviderFailure("spending_cap", fallback=True)
        current.reserved += reserved
        db.commit()
    try:
        reply = provider.extract(text, repair)
    finally:
        if reserved:
            row = db.scalar(
                select(ProviderSetting).where(ProviderSetting.id == row.id).with_for_update()
            )
            row.reserved = max(Decimal(0), row.reserved - reserved)
            row.spent += reserved
            db.commit()
    if (
        row.provider == "openrouter"
        and reply.cost is not None
        and reply.cost.is_finite()
        and reply.cost >= 0
    ):
        row = db.scalar(
            select(ProviderSetting).where(ProviderSetting.id == row.id).with_for_update()
        )
        row.spent = max(Decimal(0), row.spent - reserved + reply.cost)
        db.commit()
    return reply


def extract(db: Session, settings: Settings, text: str, *, factory=adapter):
    reasons = []
    owner = db.scalar(select(Owner))
    cloud = bool(owner and owner.settings.get("cloud_fallback", False))
    for row in ensure_providers(db):
        if not row.enabled or (
            row.cooldown_until and aware(row.cooldown_until) > datetime.now(UTC)
        ):
            continue
        remote = (
            row.provider != "ollama" or row.config.get("remote", False) or ":cloud" in row.model
        )
        if remote and not cloud and row.provider != "ollama":
            continue
        try:
            if row.provider == "chatgpt" and factory is adapter:
                from app.providers.chatgpt import connection

                connection(db, row, settings)
            provider = factory(row, settings)
            if row.provider == "ollama" and hasattr(provider, "inspect_model"):
                info = provider.inspect_model()
                if (
                    row.config.get("pinned_digest")
                    and row.config["pinned_digest"] != info["model_digest"]
                ):
                    raise ProviderFailure(
                        "The pinned Ollama model changed. Review and pin the new version in Settings."
                    )
                row.config = {**row.config, **info}
                remote = info["remote"]
            if remote and not cloud:
                row.last_status = "cloud_disabled"
                db.commit()
                continue
            reply = billed_call(db, row, provider, text)
            try:
                value = decode_extraction(reply.text, text)
            except (ValidationError, ValueError):
                reply = billed_call(db, row, provider, text, reply.text)
                try:
                    value = decode_extraction(reply.text, text)
                except (ValidationError, ValueError):
                    row.last_status = "output_needs_review"
                    db.commit()
                    raise InvalidExtraction(
                        f"{row.provider} returned details that need checking.",
                        row.provider,
                        row.model,
                    ) from None
            row.last_status, row.failures, row.cooldown_until = "online", 0, None
            db.commit()
            return value, {
                "provider": row.provider,
                "model": reply.model or row.model,
                "version": row.config.get("model_digest", ""),
                "fallback_reasons": reasons,
                "cloud": remote,
                "cost": str(reply.cost) if reply.cost is not None else None,
            }
        except ProviderFailure as failure:
            row.last_status = failure.reason[:80]
            failure.provider, failure.model = row.provider, row.model
            if not failure.fallback:
                db.commit()
                raise
            row.failures += 1
            row.cooldown_until = datetime.now(UTC) + timedelta(
                minutes=5 if row.failures == 1 else 30
            )
            reasons.append({"provider": row.provider, "reason": failure.reason})
            db.commit()
    raise WaitForResource(
        "AI is paused: no enabled provider is available. Printed text and notes are searchable."
    )
