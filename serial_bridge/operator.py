"""Operator REST and WebSocket adapters for the Hub Web UI."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from serial_bridge.auth import (
    _is_loopback,
    _require_operator_access,
    _require_send_access,
    _send_authorized,
    _who_for,
    origin_allowed,
)
from serial_bridge.constants import SESSION_LOG_ROUTE
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


def _assigned_session_log(target: object) -> Path:
    target_name, error = _resolve_target(target)
    if error is not None:
        raise HTTPException(status_code=400, detail=error)
    path = _get_hub().ports[target_name].get("log")
    if not path or not Path(path).is_file():
        raise HTTPException(status_code=404, detail="no current Session Log")
    return Path(path)


def _iter_session_log_snapshot(path: Path, size: int):
    with path.open("rb") as handle:
        remaining = size
        while remaining > 0:
            chunk = handle.read(min(remaining, 65536))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def reveal_session_log(path: Path) -> None:
    resolved = path.resolve()
    if sys.platform == "win32":
        subprocess.Popen(["explorer", f"/select,{resolved}"])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(resolved)])
    else:
        subprocess.Popen(["xdg-open", str(resolved.parent)])


class ModeBody(BaseModel):
    mode: str = Field(description="bridge or crt")


class SlotBindingBody(BaseModel):
    name: str = Field(min_length=1, max_length=32, pattern=r"^[a-z][a-z0-9_]{0,31}$")
    title: str = Field(min_length=1, max_length=64)
    com: str = Field(min_length=1)
    baud: int = Field(gt=0, strict=True)


class BindingsBody(BaseModel):
    slots: list[SlotBindingBody] = Field(min_length=1, max_length=2)
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

    @app.get("/api/agent_log", dependencies=[Depends(_require_operator_access)])
    async def api_agent_log() -> dict[str, Any]:
        return {"ok": True, "entries": await offload(_get_hub().get_agent_log)}

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

    @app.get(SESSION_LOG_ROUTE, dependencies=[Depends(_require_send_access)])
    async def api_session_log(target: str) -> StreamingResponse:
        path = _assigned_session_log(target)
        size = path.stat().st_size
        headers = {
            "Content-Disposition": f'attachment; filename="{path.name}"',
            "Content-Length": str(size),
        }
        return StreamingResponse(
            _iter_session_log_snapshot(path, size),
            media_type="text/plain; charset=utf-8",
            headers=headers,
        )

    @app.post(
        f"{SESSION_LOG_ROUTE}/reveal",
        dependencies=[Depends(_require_operator_access)],
    )
    async def api_reveal_session_log(target: str) -> dict[str, Any]:
        path = _assigned_session_log(target)
        reveal_session_log(path)
        return {"ok": True}

    app.websocket("/ws")(ws_endpoint)
