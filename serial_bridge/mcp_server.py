"""Agent-facing MCP tools and HTTP mount assembly for the Hub."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from serial_bridge.auth import McpBearerAuth
from serial_bridge.constants import TAIL_DEFAULT_N
from serial_bridge.hub import Hub
from serial_bridge.hub.queue import ExecSpec
from serial_bridge.offload import offload

_get_hub: Callable[[], Hub]


async def serial_status() -> dict[str, Any]:
    """Return Hub mode and each Target's Port Binding, open/busy hints, and the current Session Log (`log` filesystem path on the Hub host; relative `log_url` for a Bearer GET of that file from the same origin as /mcp). Empty log/log_url means none assigned. Use serial_tail for a Tail (last N lines). Do not pull the Session Log into serial_exec output."""
    hub = _get_hub()
    result = await offload(hub.status)
    await offload(hub.record_agent_read, "status", result)
    return result


async def serial_exec(
    target: str,
    cmd: str,
    prompt: str | None = None,
    prompt_is_regex: bool = False,
    prompt_settle_ms: int = 0,
    grep: str | None = None,
    grep_is_regex: bool = False,
    grep_context: int = 0,
    grep_invert: bool = False,
    max_lines: int | None = None,
    exit_code: bool = False,
) -> dict[str, Any]:
    """Run one text command through the Hub and capture its serial output (Echo and matched prompt removed). Shell Targets: exit_code=true reports the remote exit status. Prompt-first consoles: prompt + prompt_settle_ms. Trim at the source with grep (grep_invert drops matches) and max_lines (keeps the tail)."""
    return await offload(
        _get_hub().exec,
        ExecSpec(
            target=target,
            cmd=cmd,
            prompt=prompt,
            prompt_is_regex=prompt_is_regex,
            prompt_settle_ms=prompt_settle_ms,
            grep=grep,
            grep_is_regex=grep_is_regex,
            grep_context=grep_context,
            grep_invert=grep_invert,
            max_lines=max_lines,
            exit_code=exit_code,
        ),
    )


async def serial_send(
    target: str,
    cmd: str = "",
    raw_hex: str | None = None,
) -> dict[str, Any]:
    """Send one text line or hex-encoded Raw Payload without waiting for RX."""
    return await offload(
        _get_hub().send, target, cmd, who="agent", raw_hex=raw_hex
    )


async def serial_tail(
    target: str,
    n: int = TAIL_DEFAULT_N,
    with_timestamps: bool = False,
) -> dict[str, Any]:
    """Return a Tail of the current Session Log: last n lines (default 40, max 200) for one Target Name, each reduced to direction (<<< rx, >>> tx) and text; with_timestamps adds HH:MM:SS.mmm. The whole file is log_url from serial_status, not this tool."""
    hub = _get_hub()
    result = await offload(hub.tail, target, n, with_timestamps)
    await offload(
        hub.record_agent_read,
        "tail",
        result,
        target=result.get("target") or None,
        n=result.get("n"),
    )
    return result


def create_mcp(get_hub: Callable[[], Hub]) -> FastMCP:
    """Create the MCP server with serial_status, serial_exec, serial_send, and serial_tail tools."""
    global _get_hub
    _get_hub = get_hub
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
    app.mount("/", McpBearerAuth(mcp.streamable_http_app()), name="mcp")
