"""Run on the PC with the browser. Passwords are entered only at OpenAI."""

import argparse
import hashlib
import json
import os
import secrets
import time
import webbrowser
from base64 import urlsafe_b64encode
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from oauth_crypto import ISSUER, RESOURCE, SCOPE, TOKEN, credential_record, seal


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="expo-host.json")
    parser.add_argument("--output", default="chatgpt-connection.expo")
    parser.add_argument("--no-browser", action="store_true", help="Print the sign-in link without opening a browser")
    args = parser.parse_args()
    host = json.loads(Path(args.host).read_text())
    state, nonce, verifier = (secrets.token_urlsafe(48) for _ in range(3))
    returned = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            query = parse_qs(urlsplit(self.path).query)
            valid = urlsplit(self.path).path == "/auth/callback" and secrets.compare_digest(
                query.get("state", [""])[0], state
            )
            self.send_response(200 if valid else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            if valid:
                returned.update({key: values[0] for key, values in query.items()})
            self.wfile.write(
                b"Return to the Expo Buddy helper." if valid else b"Invalid callback."
            )

    with HTTPServer(("127.0.0.1", 0), Callback) as server:
        server.timeout = 1
        redirect = f"http://127.0.0.1:{server.server_port}/auth/callback"
        client_id = host.get("client_id") or "dynamic_agent_client"
        params = {
            "client_id": client_id,
            "ext_agent_host_id": host["host_id"],
            "response_type": "code",
            "redirect_uri": redirect,
            "scope": SCOPE,
            "resource": RESOURCE,
            "state": state,
            "nonce": nonce,
            "code_challenge_method": "S256",
            "code_challenge": urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("="),
        }
        if client_id == "dynamic_agent_client":
            params["agent_name_hint"] = "Expo Buddy"
        authorization_url = ISSUER + "/api/accounts/authorize?" + urlencode(params)
        print("Open this link on this PC to connect ChatGPT:", flush=True)
        print(authorization_url, flush=True)
        if not args.no_browser:
            webbrowser.open(authorization_url)
        print("Sign in only in the OpenAI browser page. Waiting up to ten minutes.")
        deadline = time.monotonic() + 600
        while not returned and time.monotonic() < deadline:
            server.handle_request()
    if not returned or returned.get("error") or not returned.get("code"):
        raise SystemExit("Sign-in was cancelled or expired. Start again.")
    issued = returned.get("client_id", client_id)
    if (
        issued == "dynamic_agent_client"
        or client_id != "dynamic_agent_client"
        and issued != client_id
    ):
        raise SystemExit("The issued client ID did not match the sign-in attempt.")
    with httpx.Client(timeout=30) as client:
        result = client.post(
            TOKEN,
            data={
                "grant_type": "authorization_code",
                "client_id": issued,
                "code": returned["code"],
                "code_verifier": verifier,
                "redirect_uri": redirect,
                "resource": RESOURCE,
            },
        )
        if result.is_error:
            raise SystemExit("OpenAI did not complete sign-in. Start a new attempt.")
        token_value = result.json()
        if not token_value.get("access_token") or not token_value.get("id_token"):
            raise SystemExit("OpenAI returned an incomplete connection. Start a new attempt.")
        credentials = credential_record(
            token_value, issued, nonce, host["host_id"], client=client
        )
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(seal(credentials, host), stream)
    print(
        f"Saved protected connection to {args.output}. Import in Expo Buddy Settings, then delete the transfer file."
    )


if __name__ == "__main__":
    main()
