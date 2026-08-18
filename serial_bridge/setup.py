"""Setup Page payload building and HTTP routes for Agent wiring."""
from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse
from serial_bridge.auth import _is_loopback, _require_operator_access
from serial_bridge.constants import HUB_PORT
from serial_bridge.token_store import (
    env_overrides_token,
    rotate_access_token,
    runtime_access_token,
)


def detect_lan_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return None


def _setup_host() -> str:
    return detect_lan_ip() or "127.0.0.1"


def _hub_mcp_url(host: str) -> str:
    return f"http://{host}:{HUB_PORT}/mcp"


def _cursor_snippet(host: str, token: str) -> str:
    payload = {
        "mcpServers": {
            "serial-bridge": {
                "url": _hub_mcp_url(host),
                "headers": {"Authorization": f"Bearer {token}"},
            }
        }
    }
    return json.dumps(payload, indent=2)


def setup_payload(*, loopback: bool) -> dict[str, Any]:
    host = _setup_host()
    payload: dict[str, Any] = {
        "loopback": loopback,
        "hub_url": _hub_mcp_url(host),
        "snippet_host": host,
        "auth_note": (
            f"Set URL to {_hub_mcp_url('<hub-host>')} and send "
            "Authorization: Bearer <access-token> on every MCP request."
        ),
    }
    if loopback:
        token = runtime_access_token()
        payload["token"] = token
        payload["cursor_snippet"] = _cursor_snippet(host, token)
        payload["env_override"] = env_overrides_token()
        if payload["env_override"]:
            payload["warning"] = (
                "SERIAL_BRIDGE_TOKEN is set in the environment, so this process "
                "still uses that value until you unset it or restart without it."
            )
    return payload


def register_setup_routes(app: FastAPI, static_dir: Path) -> None:
    @app.get("/setup")
    async def setup_page() -> FileResponse:
        return FileResponse(static_dir / "setup.html")

    @app.get("/api/setup")
    async def api_setup(request: Request) -> dict[str, Any]:
        loopback = _is_loopback(request.client.host if request.client else None)
        return setup_payload(loopback=loopback)

    @app.post("/api/setup/rotate", dependencies=[Depends(_require_operator_access)])
    async def api_setup_rotate() -> dict[str, Any]:
        rotate_access_token()
        payload = setup_payload(loopback=True)
        payload["rotated"] = True
        return payload
