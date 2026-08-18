"""Operator REST and WebSocket adapters for the Hub Web UI."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from serial_bridge.auth import (
    _is_loopback,
    _require_operator_access,
    _require_send_access,
    _send_authorized,
    _who_for,
    origin_allowed,
)
from serial_bridge.hub import available_ports
from serial_bridge.offload import offload


def _get_hub():
    from serial_bridge import app as app_module

    return app_module.hub


def _resolve_target(target: object) -> tuple[str | None, str | None]:
    return _get_hub().resolve_target(target)


def _send(target: object, cmd: str, who: str) -> dict[str, Any]:
    target_name, error = _resolve_target(target)
    if error is not None:
        return {"ok": False, "error": error}
    assert target_name is not None
    return _get_hub().send(target_name, cmd, who=who)


class ModeBody(BaseModel):
    mode: str = Field(description="bridge or crt")


class SlotBindingBody(BaseModel):
    name: str = Field(min_length=1, max_length=32, pattern=r"^[a-z][a-z0-9_]{0,31}$")
    title: str = Field(min_length=1, max_length=64)
    com: str = Field(min_length=1)
    baud: int = Field(gt=0, strict=True)


class BindingsBody(BaseModel):
    slots: list[SlotBindingBody] = Field(min_length=2, max_length=2)
    live_dir: str | None = Field(default=None, min_length=1)


class SendBody(BaseModel):
    target: str
    cmd: str


async def ws_endpoint(ws: WebSocket) -> None:
    hub = _get_hub()
    origin = ws.headers.get("origin")
    if not origin_allowed(origin):
        await ws.close(code=1008)
        return
    await ws.accept()
    hub.clients.add(ws)
    await ws.send_text(json.dumps({"type": "status", **hub.status()}, ensure_ascii=False))
    host = ws.client.host if ws.client else None
    authorization = ws.headers.get("authorization")
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "send":
                if _send_authorized(host, authorization):
                    target = msg.get("target", "")
                    cmd = msg.get("cmd", "")
                    result = await offload(
                        _send, target, cmd, _who_for(authorization)
                    )
                else:
                    result = {"ok": False, "error": "Unauthorized"}
                await ws.send_text(json.dumps({"type": "ack", **result}, ensure_ascii=False))
            elif msg.get("type") == "mode":
                if _is_loopback(host):
                    mode = msg.get("mode", "")
                    result = await offload(
                        hub.start_bridge if mode == "bridge" else hub.stop_bridge
                    )
                else:
                    result = {"ok": False, "error": "Mode changes are loopback-only"}
                await ws.send_text(json.dumps({"type": "ack", **result}, ensure_ascii=False))
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.discard(ws)


def register_operator_routes(app: FastAPI, static_dir: Path) -> None:
    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/api/status")
    async def api_status() -> dict[str, Any]:
        return await offload(_get_hub().status)

    @app.get("/api/ports", dependencies=[Depends(_require_operator_access)])
    async def api_ports() -> dict[str, Any]:
        return {"ok": True, "ports": await offload(available_ports)}

    @app.post("/api/mode", dependencies=[Depends(_require_operator_access)])
    async def api_mode(body: ModeBody) -> dict[str, Any]:
        hub = _get_hub()
        mode = body.mode.lower().strip()
        if mode == "bridge":
            return await offload(hub.start_bridge)
        if mode in ("crt", "securecrt"):
            return await offload(hub.stop_bridge)
        return {"ok": False, "error": "mode must be bridge or crt"}

    @app.post("/api/bindings", dependencies=[Depends(_require_operator_access)])
    async def api_bindings(body: BindingsBody) -> dict[str, Any]:
        hub = _get_hub()
        slots = [slot.model_dump() for slot in body.slots]
        return await offload(hub.update_slots, slots, body.live_dir)

    @app.post("/api/send", dependencies=[Depends(_require_send_access)])
    async def api_send(
        body: SendBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        return await offload(_send, body.target, body.cmd, _who_for(authorization))

    @app.get("/api/tail")
    async def api_tail(target: str = "both", n: int = 80) -> dict[str, Any]:
        return {"ok": True, "lines": _get_hub().get_tail(target, n)}

    app.websocket("/ws")(ws_endpoint)
