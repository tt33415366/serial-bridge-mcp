"""Agent-facing MCP tools and HTTP mount assembly for the Hub."""
from __future__ import annotations

from functools import partial
from typing import Any

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from serial_bridge.auth import McpBearerAuth
from serial_bridge.constants import TAIL_DEFAULT_N
from serial_bridge.hub import Hub
from serial_bridge.hub.queue import exec_result
from serial_bridge.offload import offload


def _get_hub() -> Hub:
    from serial_bridge import app as app_module

    return app_module.hub


def _resolve_target(target: object) -> tuple[str | None, str | None]:
    return _get_hub().resolve_target(target)


async def serial_status() -> dict[str, Any]:
    """Return Hub mode and each Target's Port Binding, open/busy hints, and the current Session Log (`log` filesystem path on the Hub host; relative `log_url` for a Bearer GET of that file from the same origin as /mcp). Empty log/log_url means none assigned. Use serial_tail for a Tail (last N lines). Do not pull the Session Log into serial_exec output."""
    return await offload(_get_hub().status)


async def serial_exec(
    target: str,
    cmd: str,
    prompt: str | None = None,
    prompt_is_regex: bool = False,
    grep: str | None = None,
    grep_is_regex: bool = False,
    grep_context: int = 0,
) -> dict[str, Any]:
    """Run one text command through the Hub and capture its serial output."""
    target_name, error = _resolve_target(target)
    if error is not None:
        if target_name is not None:
            return await offload(
                partial(exec_result, target_name, ok=False, error=error)
            )
        return await offload(partial(exec_result, "", ok=False, error=error))
    assert target_name is not None
    hub = _get_hub()
    return await offload(
        hub.exec,
        target_name,
        cmd,
        prompt=prompt,
        prompt_is_regex=prompt_is_regex,
        grep=grep,
        grep_is_regex=grep_is_regex,
        grep_context=grep_context,
    )


async def serial_send(
    target: str,
    cmd: str = "",
    raw_hex: str | None = None,
) -> dict[str, Any]:
    """Send one text line or hex-encoded Raw Payload without waiting for RX."""
    target_name, error = _resolve_target(target)
    if error is not None:
        return {"ok": False, "error": error}
    assert target_name is not None
    return await offload(
        _get_hub().send, target_name, cmd, who="agent", raw_hex=raw_hex
    )


async def serial_tail(
    target: str,
    n: int = TAIL_DEFAULT_N,
) -> dict[str, Any]:
    """Return a Tail of the current Session Log: last n lines (default 80, max 200) for one Target Name. The whole file is log_url from serial_status, not this tool."""
    return await offload(_get_hub().tail, target, n)


def create_mcp() -> FastMCP:
    """Create the MCP server with serial_status, serial_exec, serial_send, and serial_tail tools."""
    mcp = FastMCP(
        "Serial Bridge",
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        ),
    )
    mcp.tool()(serial_status)
    mcp.tool()(serial_exec)
    mcp.tool()(serial_send)
    mcp.tool()(serial_tail)
    return mcp


def mount_mcp(app: FastAPI, mcp: FastMCP) -> None:
    """Mount the MCP Streamable HTTP app behind Bearer auth."""
    app.mount("/", McpBearerAuth(mcp.streamable_http_app(), path="/mcp"), name="mcp")
