import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.core.config import Settings
from app.pipeline.embeddings import encode, version


def start(settings: Settings):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            return

        def do_POST(self):
            if self.path != "/embed" or not hmac.compare_digest(
                self.headers.get("Authorization", ""), "Bearer " + settings.internal_token
            ):
                self.send_error(403)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 256000:
                    self.send_error(413)
                    return
                body = json.loads(self.rfile.read(length))
                texts = body["texts"]
                if (
                    not isinstance(texts, list)
                    or not 1 <= len(texts) <= 32
                    or any(not isinstance(text, str) or len(text) > 16000 for text in texts)
                ):
                    self.send_error(400)
                    return
                result = {
                    "vectors": encode(texts, settings, query=bool(body.get("query"))),
                    "model_version": version(settings),
                }
                data = json.dumps(result).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception:
                try:
                    self.send_error(503, "Local search model is not available")
                except (BrokenPipeError, ConnectionResetError):
                    pass

    server = ThreadingHTTPServer(("0.0.0.0", 8001), Handler)  # noqa: S104 — internal Docker network, bearer protected
    threading.Thread(target=server.serve_forever, daemon=True, name="local-search").start()
    return server
