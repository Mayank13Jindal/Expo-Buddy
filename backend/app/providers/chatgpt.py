import json
import time

import httpx
from sqlalchemy import select

from app.core.secrets import cipher
from app.db.intelligence import ProviderSetting
from app.providers.base import ProviderFailure, ProviderReply, check_response
from app.providers.oauth_crypto import RESOURCE, TOKEN
from app.providers.schema import INSTRUCTIONS, extraction_schema


def account_store(row, settings):
    if not row.encrypted_secret:
        return {"accounts": {}, "active": None}
    return json.loads(cipher(settings).decrypt(row.encrypted_secret.encode()))


def save_store(row, settings, store):
    row.encrypted_secret = cipher(settings).encrypt(json.dumps(store).encode()).decode()


def connection(db, row, settings, *, client=None):
    row = db.scalar(
        select(ProviderSetting)
        .where(ProviderSetting.id == row.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    store = account_store(row, settings)
    account = store["accounts"].get(store["active"])
    if not account:
        raise ProviderFailure("Sign in with ChatGPT in Settings.", fallback=True)
    if "chatgpt.tokens.use.direct" not in account["scopes"]:
        raise ProviderFailure(
            "This ChatGPT connection has no plan-usage permission. Reconnect in Settings."
        )
    if account["expires_at"] < time.time() + 90:
        if not account.get("refresh_token"):
            raise ProviderFailure("ChatGPT sign-in expired. Reconnect in Settings.")
        web = client or httpx.Client(timeout=30)
        try:
            response = web.post(
                TOKEN,
                data={
                    "grant_type": "refresh_token",
                    "client_id": account["client_id"],
                    "refresh_token": account["refresh_token"],
                    "resource": RESOURCE,
                },
            )
            if response.is_error:
                raise ProviderFailure(
                    "ChatGPT needs reconnection."
                    if response.status_code < 500
                    else "ChatGPT refresh unavailable.",
                    fallback=response.status_code >= 500,
                )
            value = response.json()
            account = {
                **account,
                **value,
                "scopes": value.get("scope", " ".join(account["scopes"])).split(),
                "expires_at": time.time() + int(value["expires_in"]),
            }
            store["accounts"][store["active"]] = account
            save_store(row, settings, store)
            db.commit()
        except httpx.HTTPError:
            raise ProviderFailure("ChatGPT refresh unavailable.", fallback=True) from None
    if "chatgpt.tokens.use.direct" not in account["scopes"]:
        raise ProviderFailure("ChatGPT plan permission was removed. Reconnect in Settings.")
    db.commit()
    return account


class ChatGPT:
    def __init__(self, token, model, client=None):
        self.token, self.model = token, model
        self.client = client or httpx.Client(timeout=600)

    def extract(self, text, repair=None):
        if repair:
            text += "\nRepair using only supplied sources:\n" + repair[:16000]
        payload = {
            "model": self.model,
            "instructions": INSTRUCTIONS,
            "input": [{"role": "user", "content": text}],
            "store": False,
            "stream": True,
            "tools": [],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "expo_extraction",
                    "strict": True,
                    "schema": extraction_schema(),
                }
            },
        }
        chunks, completed, model = [], False, self.model
        try:
            with self.client.stream(
                "POST",
                RESOURCE + "/responses",
                headers={"Authorization": "Bearer " + self.token},
                json=payload,
            ) as response:
                check_response(response, provider="chatgpt")
                data = []
                for line in response.iter_lines():
                    if line.startswith("data:"):
                        data.append(line[5:].strip())
                        continue
                    if line or not data:
                        continue
                    raw, data = "\n".join(data), []
                    if raw == "[DONE]":
                        continue
                    event = json.loads(raw)
                    kind = event.get("type")
                    if kind == "response.output_text.delta":
                        chunks.append(event.get("delta", ""))
                        if sum(map(len, chunks)) > 200000:
                            raise ProviderFailure("ChatGPT output exceeded the extraction limit.")
                    elif kind in ("response.failed", "error", "response.incomplete"):
                        code = event.get("response", {}).get("error", event.get("error", {})) or {}
                        code = event.get("code") or code.get("code", "incomplete")
                        limit = code in (
                            "subscription_sharing_usage_limit_exceeded",
                            "subscription_sharing_usage_unavailable",
                            "rate_limit_exceeded",
                        )
                        raise ProviderFailure("ChatGPT: " + str(code)[:120], fallback=limit)
                    elif kind == "response.completed":
                        completed = True
                        model = event.get("response", {}).get("model", self.model)
        except (httpx.HTTPError, ValueError):
            raise ProviderFailure("ChatGPT stream interrupted.", fallback=True) from None
        if not completed:
            raise ProviderFailure("ChatGPT stream ended before completion.", fallback=True)
        return ProviderReply("".join(chunks), model=model)
