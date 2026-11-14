import json
import re

import httpx

from app.providers.base import ProviderFailure, ProviderReply, check_response, request
from app.providers.schema import INSTRUCTIONS, extraction_schema


class Ollama:
    def __init__(
        self, base_url: str, model: str, client: httpx.Client | None = None, *, timeout=600
    ):
        self.base_url, self.model = base_url.rstrip("/"), model
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(timeout, connect=10), trust_env=False
        )

    def inspect_model(self):
        try:
            response = self.client.get(self.base_url + "/api/tags", timeout=10)
            check_response(response, provider="ollama")
            item = next(
                (
                    item
                    for item in response.json().get("models", [])
                    if item.get("name") == self.model
                ),
                None,
            )
            if not item:
                raise ProviderFailure("model_missing", fallback=True)
            return {
                "remote": bool(
                    item.get("remote_model") or item.get("remote_host") or ":cloud" in self.model
                ),
                "model_digest": item.get("digest", ""),
            }
        except httpx.TimeoutException:
            raise ProviderFailure("timeout", fallback=True) from None
        except httpx.RequestError:
            raise ProviderFailure("unreachable", fallback=True) from None
        except (TypeError, KeyError, ValueError):
            raise ProviderFailure(
                "Ollama returned model information that needs checking."
            ) from None

    def extract(self, text: str, repair: str | None = None, *, images=None) -> ProviderReply:
        schema = extraction_schema()
        labels = list(dict.fromkeys(re.findall(r"(?m)^Page (P\d+) \[[0-9a-f-]{36}\]", text)))
        if labels:
            schema["$defs"]["Evidence"]["properties"]["page_id"]["enum"] = labels
        messages = [
            {"role": "system", "content": INSTRUCTIONS + "\nJSON schema:\n" + json.dumps(schema)},
            {"role": "user", "content": text},
        ]
        if images:
            messages[1]["images"] = images
        if repair:
            messages += [
                {"role": "assistant", "content": repair[:16000]},
                {
                    "role": "user",
                    "content": "Correct the JSON against source and schema. Include printed company, website and contact details; attach job titles to named people. Copy exact Page labels.",
                },
            ]
        result = request(
            self.client,
            self.base_url + "/api/chat",
            json={
                "model": self.model,
                "stream": False,
                "think": False,
                "format": schema,
                "messages": messages,
                "options": {"temperature": 0, "num_ctx": 8192},
            },
        )
        check_response(result, provider="ollama")
        try:
            return ProviderReply(result.json()["message"]["content"], model=self.model)
        except (KeyError, ValueError, TypeError):
            return ProviderReply("", model=self.model)
