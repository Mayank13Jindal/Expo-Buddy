from decimal import Decimal, InvalidOperation

import httpx

from app.providers.base import ProviderFailure, ProviderReply, check_response, request
from app.providers.schema import INSTRUCTIONS, extraction_schema


class OpenRouter:
    def __init__(self, model: str, key: str, client: httpx.Client | None = None):
        self.model = model
        self.client = client or httpx.Client(timeout=120)
        self.headers = {"Authorization": "Bearer " + key}

    def maximum_cost(self, text: str, repair: str | None = None) -> Decimal:
        try:
            response = self.client.get("https://openrouter.ai/api/v1/models", headers=self.headers)
            check_response(response, provider="openrouter")
            model = next(model for model in response.json()["data"] if model["id"] == self.model)
            pricing = model["pricing"]
            # UTF-8 byte count bounds text BPE tokens; include schema/instructions and framing.
            source = text + (repair or "") + INSTRUCTIONS + str(extraction_schema())
            tokens = len(source.encode()) + 1024
            return (
                Decimal(pricing["prompt"]) * tokens
                + Decimal(pricing["completion"]) * 4096
                + Decimal(pricing.get("request", "0"))
            )
        except (httpx.HTTPError, KeyError, ValueError, StopIteration, InvalidOperation):
            raise ProviderFailure(
                "Model pricing is unavailable; OpenRouter is paused.", fallback=True
            ) from None

    def extract(self, text: str, repair: str | None = None) -> ProviderReply:
        messages = [{"role": "system", "content": INSTRUCTIONS}, {"role": "user", "content": text}]
        if repair:
            messages += [
                {"role": "assistant", "content": repair[:16000]},
                {"role": "user", "content": "Repair this JSON using only the source and schema."},
            ]
        response = request(
            self.client,
            "https://openrouter.ai/api/v1/chat/completions",
            headers=self.headers,
            json={
                "model": self.model,
                "messages": messages,
                "max_tokens": 4096,
                "provider": {"require_parameters": True},
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "expo_extraction",
                        "strict": True,
                        "schema": extraction_schema(),
                    },
                },
            },
        )
        check_response(response, provider="openrouter")
        try:
            data = response.json()
            cost = data.get("usage", {}).get("cost")
            return ProviderReply(
                data["choices"][0]["message"]["content"],
                Decimal(str(cost)) if cost is not None else None,
                data.get("model", self.model),
            )
        except (ValueError, KeyError, TypeError):
            return ProviderReply("", model=self.model)
