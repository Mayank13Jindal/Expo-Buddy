"""OpenAI's PC loopback callback; Docker publishes this listener on host loopback only."""

import hashlib
import secrets
import threading
import time
from base64 import urlsafe_b64encode
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from app.providers.oauth_crypto import ISSUER, RESOURCE, SCOPE, TOKEN, credential_record


class LoopbackSignIn:
    def __init__(self, port, host_id, save, bind="127.0.0.1"):
        self.host_id, self.save = host_id, save
        self.lock = threading.Lock()
        self.pending = None
        self.result = {"state": "idle", "message": ""}
        flow = self

        class Callback(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def setup(self):
                super().setup()
                self.connection.settimeout(5)

            def do_GET(self):
                query = {
                    key: values[0] for key, values in parse_qs(urlsplit(self.path).query).items()
                }
                code, message = 400, "Invalid or expired sign-in. Start again in Expo Buddy."
                with flow.lock:
                    attempt = flow.pending
                    if (
                        urlsplit(self.path).path == "/auth/callback"
                        and attempt
                        and time.monotonic() < attempt["deadline"]
                        and secrets.compare_digest(query.get("state", "").encode(), attempt["state"].encode())
                    ):
                        flow.pending = None
                        try:
                            if query.get("error") or not query.get("code"):
                                raise ValueError("Sign-in was cancelled. Start again when ready.")
                            issued = query.get("client_id", attempt["client_id"])
                            if issued == "dynamic_agent_client" or (
                                attempt["client_id"] != "dynamic_agent_client"
                                and issued != attempt["client_id"]
                            ):
                                raise ValueError(
                                    "OpenAI returned a different registration. Start again."
                                )
                            with httpx.Client(timeout=30) as web:
                                response = web.post(
                                    TOKEN,
                                    data={
                                        "grant_type": "authorization_code",
                                        "client_id": issued,
                                        "code": query["code"],
                                        "code_verifier": attempt["verifier"],
                                        "redirect_uri": attempt["redirect"],
                                        "resource": RESOURCE,
                                    },
                                )
                                response.raise_for_status()
                                value = credential_record(
                                    response.json(),
                                    issued,
                                    attempt["nonce"],
                                    flow.host_id,
                                    client=web,
                                )
                            if attempt.get("subject") and value["subject"] != attempt["subject"]:
                                raise ValueError(
                                    "This registration belongs to another account. Choose a new account instead."
                                )
                            flow.save(value)
                            flow.result = {
                                "state": "connected",
                                "message": "ChatGPT connected. Choose a model and test it in Settings.",
                            }
                            code, message = (
                                200,
                                "ChatGPT connected. You can close this tab and return to Expo Buddy.",
                            )
                        except Exception:
                            flow.result = {
                                "state": "failed",
                                "message": "OpenAI sign-in was cancelled or could not be verified. Start a fresh attempt, or use the PC helper.",
                            }
                            message = flow.result["message"]
                self.send_response(code)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(message.encode())

        self.server = ThreadingHTTPServer((bind, port), Callback)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def start(self, account):
        with self.lock:
            state, nonce, verifier = (secrets.token_urlsafe(48) for _ in range(3))
            redirect = f"http://127.0.0.1:{self.server.server_port}/auth/callback"
            client_id = account.get("client_id") or "dynamic_agent_client"
            self.pending = {
                "state": state,
                "nonce": nonce,
                "verifier": verifier,
                "redirect": redirect,
                "client_id": client_id,
                "subject": account.get("subject"),
                "deadline": time.monotonic() + 600,
            }
            self.result = {
                "state": "waiting",
                "message": "Complete OpenAI sign-in in the other tab on this server PC.",
            }
            params = {
                "client_id": client_id,
                "ext_agent_host_id": self.host_id,
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
            return {"authorization_url": ISSUER + "/api/accounts/authorize?" + urlencode(params)}

    def status(self):
        with self.lock:
            if self.pending and time.monotonic() >= self.pending["deadline"]:
                self.pending = None
                self.result = {
                    "state": "failed",
                    "message": "Sign-in expired. Start a new attempt.",
                }
            return self.result.copy()

    def cancel(self):
        with self.lock:
            self.pending = None
            self.result = {"state": "idle", "message": ""}

    def close(self):
        self.cancel()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
