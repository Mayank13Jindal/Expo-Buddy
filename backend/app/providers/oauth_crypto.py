"""SIWC primitives, also bundled with the local sign-in helper."""

import base64
import json
import secrets
import time

import httpx
import jwt
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

ISSUER = "https://auth.openai.com"
TOKEN = ISSUER + "/api/accounts/oauth/token"
RESOURCE = "https://api.openai.com/v1"
SCOPE = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"


def verify_identity(token, client_id, nonce=None, *, client=None):
    web = client or httpx.Client(timeout=20)
    header = jwt.get_unverified_header(token)
    if header.get("alg") != "RS256":
        raise ValueError("Unsupported ID-token signature.")
    response = web.get(ISSUER + "/.well-known/jwks.json")
    response.raise_for_status()
    key = next(key for key in response.json()["keys"] if key["kid"] == header["kid"])
    claims = jwt.decode(
        token,
        jwt.PyJWK.from_dict(key).key,
        algorithms=["RS256"],
        audience=client_id,
        issuer=ISSUER,
        options={"require": ["exp", "iat", "sub", "iss", "aud"]},
    )
    if nonce is not None and not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise ValueError("Sign-in nonce did not match.")
    return claims


def validate_credentials(value, *, client=None):
    if value.get("client_id") in (None, "", "dynamic_agent_client"):
        raise ValueError("An issued client ID is required.")
    claims = verify_identity(value["id_token"], value["client_id"], value["nonce"], client=client)
    if value.get("subject") != claims["sub"] or value.get("issuer") != ISSUER:
        raise ValueError("The connection identity does not match.")
    if value.get("token_type", "").lower() != "bearer" or not value.get("access_token"):
        raise ValueError("A Bearer connection is required.")
    if not isinstance(value.get("scopes"), list) or not isinstance(
        value.get("expires_at"), (int, float)
    ):
        raise ValueError("The connection metadata is incomplete.")
    return {**value, "email": claims.get("email", "ChatGPT account")}


def key_material(shared, host_id):
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=("expo-chatgpt/" + host_id).encode()
    ).derive(shared)


def seal(value, host):
    ephemeral = X25519PrivateKey.generate()
    public = X25519PublicKey.from_public_bytes(bytes.fromhex(host["public_key"]))
    key = key_material(ephemeral.exchange(public), host["host_id"])
    nonce = secrets.token_bytes(12)
    encrypted = AESGCM(key).encrypt(nonce, json.dumps(value).encode(), host["host_id"].encode())
    return {
        "host_id": host["host_id"],
        "ephemeral": ephemeral.public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        .hex(),
        "nonce": nonce.hex(),
        "payload": base64.b64encode(encrypted).decode(),
    }


def unseal(value, private, host_id):
    if value["host_id"] != host_id:
        raise ValueError("This connection belongs to a different server.")
    public = X25519PublicKey.from_public_bytes(bytes.fromhex(value["ephemeral"]))
    key = key_material(private.exchange(public), host_id)
    raw = AESGCM(key).decrypt(
        bytes.fromhex(value["nonce"]), base64.b64decode(value["payload"]), host_id.encode()
    )
    return json.loads(raw)


def credential_record(tokens, client_id, nonce, host_id, *, client=None):
    claims = verify_identity(tokens["id_token"], client_id, nonce, client=client)
    return validate_credentials(
        {
            **tokens,
            "client_id": client_id,
            "nonce": nonce,
            "subject": claims["sub"],
            "issuer": ISSUER,
            "ext_agent_host_id": host_id,
            "scopes": tokens.get("scope", "").split(),
            "expires_at": time.time() + int(tokens["expires_in"]),
        },
        client=client,
    )
