"""Bound JSON before parsing; large source files remain streamed multipart uploads."""

from starlette.responses import JSONResponse


class JSONBodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        headers = dict(scope.get("headers", []))
        if scope["type"] != "http" or not headers.get(b"content-type", b"").lower().startswith(
            b"application/json"
        ):
            await self.app(scope, receive, send)
            return
        limit = 65536 if scope["path"].startswith("/mcp") else 1024 * 1024
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > limit:
                await JSONResponse(
                    {
                        "detail": "This request is too large. Use a smaller selection or shorter text."
                    },
                    status_code=413,
                )(scope, receive, send)
                return
            if not message.get("more_body"):
                break
        delivered = False

        async def buffered_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, buffered_receive, send)
