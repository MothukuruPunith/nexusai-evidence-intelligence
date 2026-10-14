"""Bound the full multipart request before Starlette can spool unbounded file parts."""

from starlette.responses import JSONResponse

MAX_REQUEST = 6 * 1024 * 1024


class UploadBodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] not in {"/documents/upload", "/rag/query"}:
            return await self.app(scope, receive, send)
        maximum = 16 * 1024 if scope["path"] == "/rag/query" else MAX_REQUEST
        parts = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            value = message.get("body", b"")
            size += len(value)
            if size > maximum:
                response = JSONResponse(
                    status_code=413,
                    content={
                        "error": "request_too_large",
                        "request_id": scope.get("state", {}).get("request_id"),
                    },
                )
                return await response(scope, receive, send)
            parts.append(value)
            if not message.get("more_body", False):
                break
        consumed = False

        async def replay():
            nonlocal consumed
            if consumed:
                return await receive()
            consumed = True
            return {"type": "http.request", "body": b"".join(parts), "more_body": False}

        return await self.app(scope, replay, send)
