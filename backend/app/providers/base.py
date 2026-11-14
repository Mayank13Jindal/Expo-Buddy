from dataclasses import dataclass
from decimal import Decimal

import httpx


class ProviderFailure(Exception):
    def __init__(self, reason: str, *, fallback: bool = False):
        self.reason, self.fallback = reason, fallback
        super().__init__(reason)


@dataclass
class ProviderReply:
    text: str
    cost: Decimal | None = None
    model: str = ""


def check_response(response: httpx.Response, *, provider: str) -> None:
    if response.status_code in (401, 403):
        raise ProviderFailure("Permission denied. Check this provider in Settings.")
    if response.status_code == 404 and provider == "ollama":
        raise ProviderFailure("model_missing", fallback=True)
    if response.status_code in (402, 429):
        raise ProviderFailure(
            "spending_cap" if provider == "openrouter" else "plan_limit", fallback=True
        )
    if response.status_code >= 500:
        raise ProviderFailure("unreachable", fallback=True)
    if response.is_error:
        raise ProviderFailure("Provider rejected this request. Check its settings.")


def request(client: httpx.Client, url: str, **kwargs) -> httpx.Response:
    try:
        return client.post(url, **kwargs)
    except httpx.TimeoutException:
        raise ProviderFailure("timeout", fallback=True) from None
    except httpx.RequestError:
        raise ProviderFailure("unreachable", fallback=True) from None
