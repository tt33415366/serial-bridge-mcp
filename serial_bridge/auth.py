"""Loopback, Bearer, and Operator-origin access checks for HTTP, WebSocket, and MCP."""
from __future__ import annotations

from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse
from serial_bridge.constants import HUB_PORT
from serial_bridge.token_store import get_token_store
from starlette.types import ASGIApp, Receive, Scope, Send

UI_ORIGINS = {
    f"http://127.0.0.1:{HUB_PORT}",
    f"http://localhost:{HUB_PORT}",
}


def _is_loopback(host: str | None) -> bool:
    return host in {"127.0.0.1", "::1"}


def _valid_bearer(authorization: str | None) -> bool:
    try:
        return get_token_store().valid_bearer(authorization)
    except RuntimeError:
        return False


def _send_authorized(host: str | None, authorization: str | None) -> bool:
    return _is_loopback(host) or _valid_bearer(authorization)


def _who_for(authorization: str | None) -> str:
    """Derive the transcript actor server-side; clients never pick their own."""
    return "agent" if _valid_bearer(authorization) else "user"


class McpBearerAuth:
    def __init__(self, asgi_app: ASGIApp) -> None:
        self.app = asgi_app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = {
                key.decode("latin-1").lower(): value.decode("latin-1")
                for key, value in scope["headers"]
            }
            if not _valid_bearer(headers.get("authorization")):
                response = JSONResponse(
                    {"error": "Unauthorized"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def _require_operator_access(request: Request) -> None:
    if not _is_loopback(request.client.host if request.client else None):
        raise HTTPException(status_code=403, detail="Operator-only: loopback required")
    origin = request.headers.get("origin")
    if origin is not None and origin not in UI_ORIGINS:
        raise HTTPException(status_code=403, detail="Origin not allowed")


def _require_send_access(
    request: Request,
    authorization: str | None = Header(default=None),
) -> None:
    host = request.client.host if request.client else None
    if not _send_authorized(host, authorization):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )


def origin_allowed(origin: str | None) -> bool:
    return origin is None or origin in UI_ORIGINS
