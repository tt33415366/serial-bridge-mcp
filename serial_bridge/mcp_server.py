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
    """Return every DUT grouped: duts [{name, title, mode, mode_switch {allowed, busy, busy_targets, next_action} for that DUT's Targets, ports}]. ports holds that DUT's Targets keyed by Target Name (unique only within its DUT); pass the DUT name as `dut` and the Target Name as `target` to the other tools. Each Target has its Port Binding plus port_state (closed|open|lost), busy, shell (ready|unknown; ready only while the newest device output ends at the Operator-configured Target Prompt, otherwise unknown), shell_observed_at, target_prompt (read-only; the Operator-configured regex behind shell), open_error (only when present: why the Target is not open), and the current Session Log (`log` path on the Hub host; relative `log_url` for a Bearer GET from the same origin as /mcp). Empty log/log_url means none assigned. Use serial_tail for a Tail (last N lines). Do not pull the Session Log into serial_exec output."""
    hub = _get_hub()
    result = await offload(hub.agent_status)
    await offload(hub.record_agent_read, "status", result)
    return result


async def serial_exec(
    dut: str,
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
    raw: bool = False,
) -> dict[str, Any]:
    """Run one text command on one Target and capture its serial output (Echo and matched prompt removed). Returns status: completed (prompt or exit-code evidence; a nonzero exit_code is still completed), quiet or timeout (observation ended only; the command may still be running, do not resend automatically), disconnected (port lost, partial output kept), aborted, or error. completed does not mean asynchronous work such as an upgrade finished. Shell Targets: exit_code=true reports the remote exit status. Prompt-first consoles: prompt + prompt_settle_ms. Trim with grep (grep_invert drops matches) and max_lines (keeps the tail). raw=true also returns raw_base64: the first 32 KiB of the unmodified capture window (echo, ANSI, wrapper included) and raw_truncated. Address the console with `dut` (DUT Name) and `target` (Target Name), both required; a Target Name is unique only within its DUT, so linux in two DUTs are different consoles. The result echoes `dut` and `target`."""
    return await offload(
        _get_hub().exec,
        ExecSpec(
            dut=dut,
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
            raw=raw,
        ),
    )


async def serial_send(
    dut: str,
    target: str,
    cmd: str = "",
    raw_hex: str | None = None,
) -> dict[str, Any]:
    """Send one text line or hex-encoded Raw Payload without waiting for RX. Address the console with `dut` (DUT Name) and `target` (Target Name), both required; a Target Name is unique only within its DUT, so linux in two DUTs are different consoles. The result echoes `dut` and `target`."""
    return await offload(
        _get_hub().send, dut, target, cmd, who="agent", raw_hex=raw_hex
    )


async def serial_tail(
    dut: str,
    target: str,
    n: int = TAIL_DEFAULT_N,
    with_timestamps: bool = False,
) -> dict[str, Any]:
    """Return a Tail of the current Session Log: last n lines (default 40, max 200) for one Target, each reduced to direction (<<< rx, >>> tx) and text; with_timestamps adds HH:MM:SS.mmm. The whole file is log_url from serial_status, not this tool. Address the console with `dut` (DUT Name) and `target` (Target Name), both required; a Target Name is unique only within its DUT, so linux in two DUTs are different consoles. The result echoes `dut` and `target`."""
    hub = _get_hub()
    result = await offload(hub.tail, dut, target, n, with_timestamps)
    await offload(
        hub.record_agent_read,
        "tail",
        result,
        target=result.get("target") or None,
        n=result.get("n"),
    )
    return result


async def serial_set_mode(dut: str, mode: str) -> dict[str, Any]:
    """Switch ONE DUT to Bridge Mode or CRT Mode ('bridge' or 'crt'); other DUTs keep their mode and ports. `dut` (DUT Name) is required. Refused unless the Operator granted Mode Switch Permission (one switch for the whole Hub; serial_status duts[].mode_switch.allowed) and refused while any Exec is in flight on that DUT's Targets (duts[].mode_switch.busy / busy_targets; nothing is queued; an Exec on another DUT does not block). An unknown `dut` is rejected with the list of DUT Names. The result reports each Target's open outcome; Bridge Mode does not mean every port opened, so check ports and serial_status port_state. Port Bindings and port discovery stay with the Operator."""
    return await offload(_get_hub().set_mode_agent, dut, mode)


def create_mcp(get_hub: Callable[[], Hub]) -> FastMCP:
    """Create the MCP server with serial_status, serial_exec, serial_send, serial_tail, and serial_set_mode tools."""
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
    mcp.tool()(serial_set_mode)
    return mcp


def mount_mcp(app: FastAPI, mcp: FastMCP) -> None:
    """Mount the MCP Streamable HTTP app behind Bearer auth."""
    app.mount("/", McpBearerAuth(mcp.streamable_http_app()), name="mcp")
