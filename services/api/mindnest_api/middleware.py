"""Request-scoped middleware."""

from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.datastructures import MutableHeaders
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a request id to the request state and to the x-request-id response header."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id") or uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response


class SecurityHeadersMiddleware:
    """Safe defaults on every API response, including streamed ones.

    The web app sets its own stricter headers for pages; these cover the API when it is reached
    directly. Anything a route sets itself (for example a download's Content-Disposition) is kept.
    """

    def __init__(self, app: ASGIApp, *, hsts: bool) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # Swagger UI (development only) loads scripts from a CDN, so it gets no CSP.
        is_docs = scope.get("path", "").startswith("/api/docs")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Referrer-Policy", "no-referrer")
                headers.setdefault("Cache-Control", "no-store")
                headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
                if not is_docs:
                    headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
                if self.hsts:
                    headers.setdefault("Strict-Transport-Security", "max-age=31536000")
            await send(message)

        await self.app(scope, receive, send_with_headers)
