# ruff: noqa: S105 — credentials in this file are fictional test fixtures
import json
import time
from io import BytesIO
from zipfile import ZipFile

import httpx
import jwt
import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa, x25519
from sqlalchemy.orm import Session

from app.api.chatgpt_connection import host_keys
from app.domain.providers import ensure_providers, extract
from app.providers.base import ProviderFailure
from app.providers.chatgpt import ChatGPT, account_store, connection, save_store
from app.providers.oauth_crypto import ISSUER, seal, unseal, validate_credentials, verify_identity


def test_identity_validation_and_host_bound_transfer(settings):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk["kid"] = "fake-key"
    web = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"keys": [jwk]}))
    )
    claims = {
        "iss": ISSUER,
        "aud": "fake-issued-client",
        "sub": "fake-person",
        "iat": int(time.time()),
        "exp": int(time.time() + 600),
        "nonce": "fake-nonce",
        "email": "sample@example.invalid",
    }
    token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "fake-key"})
    assert (
        verify_identity(token, "fake-issued-client", "fake-nonce", client=web)["sub"]
        == "fake-person"
    )
    with pytest.raises(ValueError):
        verify_identity(token, "fake-issued-client", "wrong-nonce", client=web)
    with pytest.raises(jwt.InvalidAudienceError):
        verify_identity(token, "other-client", "fake-nonce", client=web)
    value = validate_credentials(
        {
            "id_token": token,
            "client_id": "fake-issued-client",
            "nonce": "fake-nonce",
            "subject": "fake-person",
            "issuer": ISSUER,
            "token_type": "Bearer",
            "access_token": "fake-access",
            "scopes": ["chatgpt.tokens.use.direct"],
            "expires_at": time.time() + 600,
        },
        client=web,
    )
    private, host = host_keys(settings)
    profile = {
        "host_id": host,
        "public_key": private.public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        .hex(),
    }
    protected = seal(value, profile)
    assert (
        "fake-access" not in json.dumps(protected)
        and unseal(protected, private, host)["subject"] == "fake-person"
    )
    with pytest.raises(ValueError):
        unseal(protected, private, "different-host")
    with pytest.raises(InvalidTag):
        unseal(protected, x25519.X25519PrivateKey.generate(), host)


def test_chatgpt_stream_requires_terminal_success_and_exact_model():
    requests = []

    def transport(request):
        requests.append(json.loads(request.content))
        data = [
            {"type": "response.output_text.delta", "delta": "{}"},
            {"type": "response.completed", "response": {"model": "fake-pinned"}},
        ]
        return httpx.Response(
            200, text="".join("data: " + json.dumps(item) + "\n\n" for item in data)
        )

    client = httpx.Client(transport=httpx.MockTransport(transport))
    assert ChatGPT("fake-token", "fake-pinned", client).extract("fictional source").text == "{}"
    payload = requests[0]
    assert (
        payload["model"] == "fake-pinned"
        and payload["tools"] == []
        and payload["store"] is False
        and payload["stream"] is True
    )
    assert "max_output_tokens" not in payload and "temperature" not in payload
    for kind in ("response.failed", "response.incomplete", "error"):
        data = [
            {"type": "response.output_text.delta", "delta": "{}"},
            {
                "type": kind,
                "response": {"error": {"code": "subscription_sharing_usage_limit_exceeded"}},
            },
        ]
        client = httpx.Client(
            transport=httpx.MockTransport(
                lambda request, data=data: httpx.Response(
                    200, text="".join("data: " + json.dumps(item) + "\n\n" for item in data)
                )
            )
        )
        with pytest.raises(ProviderFailure):
            ChatGPT("fake-token", "fake-pinned", client).extract("fictional")
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, text='data: {"type":"response.output_text.delta","delta":"{}"}\n\n'
            )
        )
    )
    with pytest.raises(ProviderFailure):
        ChatGPT("fake-token", "fake-pinned", client).extract("fictional")


def test_refresh_rotates_credentials_encrypted_and_permission_is_required(engine, settings):
    with Session(engine) as db:
        row = ensure_providers(db)[1]
        db.commit()
        value = {
            "access_token": "fake-old-access",
            "refresh_token": "fake-old-refresh",
            "client_id": "fake-issued",
            "expires_at": 0,
            "scopes": ["chatgpt.tokens.use.direct"],
        }
        save_store(row, settings, {"accounts": {"a": value}, "active": "a"})
        db.commit()

        def refresh(request):
            assert "fake-old-refresh" in request.content.decode()
            return httpx.Response(
                200,
                json={
                    "access_token": "fake-new-access",
                    "refresh_token": "fake-new-refresh",
                    "expires_in": 3600,
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(refresh))
        assert connection(db, row, settings, client=client)["refresh_token"] == "fake-new-refresh"
        assert "fake-new" not in row.encrypted_secret
        assert account_store(row, settings)["accounts"]["a"]["access_token"] == "fake-new-access"
        store = account_store(row, settings)
        store["accounts"]["a"]["scopes"] = []
        save_store(row, settings, store)
        db.commit()
        with pytest.raises(ProviderFailure):
            connection(db, row, settings, client=client)


def test_helper_download_has_only_public_host_profile_and_no_secrets(signed_in):
    response = signed_in.get("/api/v1/settings/providers/chatgpt/helper")
    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        profile = json.loads(archive.read("expo-host.json"))
        assert profile["host_id"].startswith("urn:uuid:") and len(profile["public_key"]) == 64
        assert set(profile) == {"host_id", "public_key", "client_id"}
        helper = archive.read("connect_helper.py").decode()
        assert (
            "127.0.0.1" in helper and "code_verifier" in helper and "dynamic_agent_client" in helper
        )
    assert (
        signed_in.post(
            "/api/v1/settings/providers/chatgpt/import",
            json={"host_id": "wrong", "ephemeral": "0" * 64, "nonce": "0" * 24, "payload": "bad"},
        ).status_code
        == 422
    )


def test_ollama_pin_change_does_not_silently_fall_back(signed_in, engine, settings):
    with Session(engine) as db:
        row = ensure_providers(db)[0]
        row.enabled = True
        row.config = {"pinned_digest": "saved-digest"}
        db.commit()

        class Fake:
            def inspect_model(self):
                return {"remote": False, "model_digest": "changed-digest"}

            def extract(self, *args):
                raise AssertionError("Pinned model was changed")

        with pytest.raises(ProviderFailure, match="pinned"):
            extract(db, settings, "fictional", factory=lambda *args: Fake())


def test_valid_import_is_encrypted_replay_protected_and_catalog_uses_active_account(
    signed_in, settings, monkeypatch
):
    from app.providers import oauth_crypto

    private, host = host_keys(settings)
    profile = {
        "host_id": host,
        "public_key": private.public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        .hex(),
    }
    value = {
        "issuer": ISSUER,
        "subject": "fictional-owner",
        "client_id": "fake-issued",
        "id_token": "fake-id",
        "nonce": "fake-nonce",
        "access_token": "fake-access",
        "refresh_token": "fake-refresh",
        "scopes": ["chatgpt.tokens.use.direct"],
        "expires_at": time.time() + 600,
        "email": "person@example.invalid",
        "ext_agent_host_id": host,
        "token_type": "Bearer",
    }
    monkeypatch.setattr("app.api.chatgpt_connection.validate_credentials", lambda value: value)
    protected = oauth_crypto.seal(value, profile)
    response = signed_in.post("/api/v1/settings/providers/chatgpt/import", json=protected)
    assert response.status_code == 200 and response.json()["inference_verified"] is False
    assert (
        signed_in.post("/api/v1/settings/providers/chatgpt/import", json=protected).status_code
        == 409
    )
    public = signed_in.get("/api/v1/settings/providers").json()
    assert "fake-access" not in json.dumps(public) and "fake-refresh" not in json.dumps(public)
    chat = next(row for row in public["providers"] if row["provider"] == "chatgpt")
    assert (
        chat["accounts"][0]["label"] == "person@example.invalid"
        and chat["accounts"][0]["plan_enabled"]
    )
    client_type = httpx.Client

    def transport(request):
        assert (
            request.url.path == "/v1/models"
            and request.headers["Authorization"] == "Bearer fake-access"
        )
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "slug": "fake-model-snapshot",
                        "display_name": "Fictional available model",
                        "visibility": "list",
                    },
                    {"slug": "fake-hidden", "visibility": "hide"},
                ]
            },
        )

    monkeypatch.setattr(
        "app.api.chatgpt_connection.httpx.Client",
        lambda **kwargs: client_type(transport=httpx.MockTransport(transport)),
    )
    response = signed_in.get("/api/v1/settings/providers/chatgpt/models")
    assert response.status_code == 200, response.text
    assert response.json()["models"] == [
        {"id": "fake-model-snapshot", "name": "Fictional available model"}
    ]


def test_helper_loopback_works_without_a_browser(tmp_path, monkeypatch, capsys):
    import importlib
    import sys
    import threading
    from http.client import HTTPConnection
    from urllib.parse import parse_qs, urlencode, urlsplit

    monkeypatch.syspath_prepend(
        str(__import__("pathlib").Path(__file__).parents[1] / "app/providers")
    )
    helper = importlib.import_module("connect_helper")
    profile = tmp_path / "host.json"
    profile.write_text(json.dumps({"host_id": "urn:uuid:fake-host", "public_key": "public"}))
    output = tmp_path / "connection.expo"
    monkeypatch.setattr(sys, "argv", ["helper", "--host", str(profile), "--output", str(output)])
    attempt = {}

    def open_browser(url):
        params = {key: value[0] for key, value in parse_qs(urlsplit(url).query).items()}
        attempt.update(params)
        callback = (
            params["redirect_uri"]
            + "?"
            + urlencode(
                {"state": params["state"], "code": "fake-code", "client_id": "fake-issued-client"}
            )
        )

        def complete():
            target = urlsplit(callback)
            connection = HTTPConnection(target.hostname, target.port, timeout=5)
            try:
                connection.request("GET", target.path + "?" + target.query)
                assert connection.getresponse().status == 200
            finally:
                connection.close()

        threading.Thread(target=complete, daemon=True).start()
        return False

    def token_exchange(request):
        form = parse_qs(request.content.decode())
        assert form["client_id"] == ["fake-issued-client"]
        assert form["redirect_uri"] == [attempt["redirect_uri"]]
        assert form["resource"] == ["https://api.openai.com/v1"]
        import hashlib
        from base64 import urlsafe_b64encode

        assert (
            urlsafe_b64encode(hashlib.sha256(form["code_verifier"][0].encode()).digest())
            .decode()
            .rstrip("=")
            == attempt["code_challenge"]
        )
        return httpx.Response(
            200, json={"access_token": "fake-access", "id_token": "fake-identity"}
        )

    web = httpx.Client(transport=httpx.MockTransport(token_exchange))
    monkeypatch.setattr(helper.webbrowser, "open", open_browser)
    monkeypatch.setattr(helper.httpx, "Client", lambda **kwargs: web)
    monkeypatch.setattr(helper, "credential_record", lambda *args, **kwargs: {"verified": True})
    monkeypatch.setattr(helper, "seal", lambda value, host: {"protected": value["verified"]})
    helper.main()
    printed = capsys.readouterr().out
    assert "https://auth.openai.com/api/accounts/authorize?" in printed
    assert attempt["redirect_uri"].startswith("http://127.0.0.1:")
    assert attempt["redirect_uri"].endswith("/auth/callback")
    assert attempt["client_id"] == "dynamic_agent_client"
    assert "chatgpt.tokens.use.direct" in attempt["scope"]
    assert json.loads(output.read_text()) == {"protected": True}
    assert output.stat().st_mode & 0o777 == 0o600


def test_direct_sign_in_callback_reconnect_and_sign_out(signed_in, settings, monkeypatch):
    from http.client import HTTPConnection
    from urllib.parse import parse_qs, urlencode, urlsplit

    from app.providers import loopback

    original_client = httpx.Client
    posted = []

    def remote(request):
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(200, json={"revocation_endpoint": ISSUER + "/revoke"})
        if request.url.path == "/revoke":
            return httpx.Response(200)
        posted.append(parse_qs(request.content.decode()))
        return httpx.Response(
            200,
            json={
                "access_token": "fictional-access",
                "id_token": "fictional-id-" + str(len(posted)),
            },
        )

    monkeypatch.setattr(
        loopback.httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(remote)),
    )
    monkeypatch.setattr(
        loopback,
        "credential_record",
        lambda tokens, client_id, nonce, host_id, **kwargs: {
            **tokens,
            "client_id": client_id,
            "nonce": nonce,
            "ext_agent_host_id": host_id,
            "issuer": ISSUER,
            "subject": "fictional-direct-owner",
            "email": "direct@example.invalid",
            "refresh_token": "fictional-refresh",
            "scopes": ["chatgpt.tokens.use.direct"],
            "expires_at": time.time() + 3600,
            "token_type": "Bearer",
        },
    )

    def complete(url, state=None):
        params = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
        target = urlsplit(params["redirect_uri"])
        assert target.hostname == "127.0.0.1" and target.path == "/auth/callback"
        connection = HTTPConnection(target.hostname, target.port, timeout=5)
        try:
            connection.request(
                "GET",
                target.path
                + "?"
                + urlencode(
                    {
                        "state": state or params["state"],
                        "code": "fictional-code",
                        "client_id": "fictional-issued-client",
                    }
                ),
            )
            response = connection.getresponse()
            response.read()
            return response.status
        finally:
            connection.close()

    first = signed_in.post("/api/v1/settings/providers/chatgpt/sign-in").json()["authorization_url"]
    assert signed_in.get("/api/v1/settings/providers/chatgpt/sign-in").json()["state"] == "waiting"
    assert complete(first, "incorrect-state") == 400
    assert complete(first) == 200
    assert complete(first) == 400
    assert posted[0]["client_id"] == ["fictional-issued-client"]
    assert posted[0]["resource"] == ["https://api.openai.com/v1"]
    assert posted[0]["code_verifier"]
    assert (
        signed_in.get("/api/v1/settings/providers/chatgpt/sign-in").json()["state"] == "connected"
    )
    providers = signed_in.get("/api/v1/settings/providers").json()["providers"]
    row = next(row for row in providers if row["provider"] == "chatgpt")
    assert row["enabled"] and row["accounts"][0]["connected"]
    assert signed_in.post("/api/v1/settings/providers/chatgpt/disconnect").json()[
        "remote_revocation_confirmed"
    ]
    row = next(
        row
        for row in signed_in.get("/api/v1/settings/providers").json()["providers"]
        if row["provider"] == "chatgpt"
    )
    assert not row["enabled"] and not row["accounts"][0]["connected"]
    second = signed_in.post("/api/v1/settings/providers/chatgpt/sign-in").json()[
        "authorization_url"
    ]
    assert parse_qs(urlsplit(second).query)["client_id"] == ["fictional-issued-client"]
    assert complete(second) == 200
    row = next(
        row
        for row in signed_in.get("/api/v1/settings/providers").json()["providers"]
        if row["provider"] == "chatgpt"
    )
    assert row["enabled"] and row["accounts"][0]["connected"]
    third = signed_in.post("/api/v1/settings/providers/chatgpt/sign-in").json()["authorization_url"]
    signed_in.post("/api/v1/settings/providers/chatgpt/disconnect")
    assert complete(third) == 400


def test_pending_direct_sign_in_can_be_cancelled(signed_in):
    response = signed_in.post('/api/v1/settings/providers/chatgpt/sign-in')
    assert response.status_code == 200
    assert signed_in.get('/api/v1/settings/providers/chatgpt/sign-in').json()['state'] == 'waiting'
    assert signed_in.delete('/api/v1/settings/providers/chatgpt/sign-in').status_code == 200
    assert signed_in.get('/api/v1/settings/providers/chatgpt/sign-in').json()['state'] == 'idle'
