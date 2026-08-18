# Serial Bridge MCP Design

Date: 2026-08-18  
Status: Approved for implementation planning  
Glossary: [`CONTEXT.md`](../../../CONTEXT.md)  
Decisions: [`docs/adr/`](../../adr/)

## Problem

Device consoles (serial) are attached to a local Windows PC. Source code and Agents often run on a remote Linux machine. The existing Serial Bridge Web UI already shares COM ports between an Operator and HTTP helpers, but Agents need a first-class MCP tool surface that works both on the PC and over the LAN—without a second process fighting for the same ports.

## Goals

- Expose **Exec**, **Send**, and **status** to Agents via MCP over HTTP.
- Keep one **Hub** as the authority for ports, mode, transcript, and queues (shared with the Web UI).
- Support remote Agents with **Bearer Access Token**; keep local UI usable via **loopback exemption**.
- Make **Port Binding** (COM + baud), **Target Name**, and **Display Title** configurable via env/CLI and Web UI persistence (exactly two **Target Slots**).
- Auto-provision a durable Access Token on first boot (secrets file), with env override and Operator Rotate.
- Provide a **Setup Page** (`/setup`) that guides MCP client wiring (Cursor snippet + generic URL/Bearer).
- Preserve Bridge Mode / CRT Mode ownership semantics (Operator-controlled).

## Non-goals (MVP)

- stdio MCP (deferred; local Agents use HTTP to loopback).
- `serial_tail` MCP tool.
- Agent-driven mode switch, Port Binding, or Target Name changes.
- Adding/removing Target Slots beyond the fixed two.
- Default per-Target prompt strings.
- Keeping `send.py`, `read.py`, `bridge.py`, `gui_app.py` on the main path.

## Architecture

Single Windows process binds `0.0.0.0:8765` (existing UI port):

- Web UI (static + WebSocket) + Setup Page
- REST adapters
- MCP Streamable HTTP endpoint (e.g. `/mcp`)
- Hub + per-Target queues + Exec engine

```text
[Remote Agent] -- Authorization: Bearer --> Hub :8765
[Local Agent]  -- Bearer --> http://127.0.0.1:8765/mcp
[Operator UI]  -- loopback --> UI / WS /api /setup secrets (writes exempt from token)

Hub
  Config (slots[]: Target Name, Display Title, Port Binding)
  Access Token (secrets file; env override)
  Targets: two Slots (defaults linux / rtos)
  Mode: bridge | crt
  TargetQueue (FIFO; Operator barge-in)
  ExecEngine (idle + optional prompt)
  Transcript + UI broadcast
```

### Logical modules

| Module | Responsibility | Depends on |
|--------|----------------|------------|
| Config | Load/merge/persist slots (name, title, COM/baud); migrate legacy `ports`; validate | — |
| TokenStore | Load/generate/persist/rotate Access Token; env override | — |
| Hub | Mode, open/close serial, transcript, WS broadcast | Config, pyserial |
| TargetQueue | Per-Target FIFO; Operator barge-in; abort on CRT | Hub |
| ExecEngine | Text-line TX; capture until idle/prompt/timeout; strip ANSI; 32KiB cap | TargetQueue |
| McpHttp | MCP tools + Bearer auth | Hub, ExecEngine, TokenStore |
| WebApp | Console UI; Setup Page; loopback-only mode/bindings/secrets; binding editor when ports free | Hub, Config, TokenStore |

Main entry remains the `app.py` line (refactored into modules as needed). Parallel entrypoints are removed.

## Targets and Port Binding

- Exactly two **Target Slots**. Defaults: Target Names `linux` / `rtos`; Display Titles `Linux` / `RTOS`.
- Each Slot: Target Name, Display Title, COM, baud.
- Target Name: `^[a-z][a-z0-9_]{0,31}$`, unique across Slots, stored lowercase; editable **only in CRT Mode**.
- Display Title: trim length 1–64; Unicode/spaces allowed; uniqueness not required; editable anytime.
- Port Binding (COM/baud): editable in CRT Mode (ports free), same panel as Target Name.
- Persisted shape: ordered `slots[]` in the config JSON. Legacy `{ "ports": { "linux": {...}, "rtos": {...} } }` is read, migrated, and rewritten.
- Load order for bindings: built-in defaults → environment/CLI → persisted config file (**file wins** for UI-saved values).
- Port env keys by **Slot index**: `SERIAL_BRIDGE_SLOT0_PORT` / `SLOT0_BAUD`, `SLOT1_*`; `SERIAL_BRIDGE_LINUX_*` / `RTOS_*` remain aliases for Slot0 / Slot1.
- Renaming a Target opens `live/<name>.log` for the new name; the previous log file is left in place (not renamed or merged).
- Agents read name, title, and bindings via `serial_status` only; they cannot change them.

Suggested env / path examples (exact names can match implementation):

- `SERIAL_BRIDGE_TOKEN` (runtime override)
- `SERIAL_BRIDGE_TOKEN_FILE` (optional path; default `serial_bridge.token` beside config)
- `SERIAL_BRIDGE_SLOT0_PORT` / `SERIAL_BRIDGE_SLOT0_BAUD` (and `SLOT1_*`)
- `SERIAL_BRIDGE_LINUX_PORT` / `SERIAL_BRIDGE_LINUX_BAUD` (aliases for Slot0)
- `SERIAL_BRIDGE_RTOS_PORT` / `SERIAL_BRIDGE_RTOS_BAUD` (aliases for Slot1)
- `SERIAL_BRIDGE_CONFIG` (optional path to JSON config file)

## Access Token

- Required header: `Authorization: Bearer <token>` for MCP HTTP and non-loopback `POST /api/send`.
- Loopback (`127.0.0.1` / `::1`) exempt for UI writes; `POST /api/mode` remains **loopback-only**.
- First boot: if no token from env/file, generate `secrets.token_urlsafe(32)` into the secrets file (not the Port Binding JSON).
- If env is already set on first boot, **mirror** that value into the secrets file; runtime authority remains env while set.
- Rotate (Setup Page, loopback only): rewrite secrets file; if env is set, warn that the process still uses env until unset / restart without it.
- Secrets file must be gitignored; never embed the token in static frontend assets.

## Setup Page

- Route: `GET /setup`, linked from the main console (and back).
- Content: Hub MCP URL, Bearer usage, copy-paste Cursor `mcpServers` snippet (`url` + `headers.Authorization`), plus a short generic URL/header note.
- Default snippet host: auto-detected LAN IP; fall back to `127.0.0.1`.
- Non-loopback may load the page for URL guidance, but **must not** receive token plaintext, Rotate, or the secret-bearing snippet.

## MCP tools

### `serial_status`

Read-only: mode; per-Target `name`, `title`, Port Binding, open flag, busy/queue hint.

### `serial_exec`

- Input: `target` (Target Name), `cmd` (text line), optional `prompt`, optional `prompt_is_regex` (default false), optional overrides for idle/total timeout later if needed.
- Behavior: enqueue → write text + configured line ending → capture RX until:
  - idle gap **1.0s** with no new bytes, or
  - optional prompt match (literal substring, or regex if `prompt_is_regex`), or
  - total wall time **60s** (`timed_out: true`).
- Post-process: strip ANSI; keep command echo; truncate to last **32 KiB** (`truncated: true`).
- Output concept: `ok`, `target`, `output`, `truncated`, `timed_out`, `aborted`.

Raw/hex is **not** supported on Exec.

### `serial_send`

- Default: text line + line ending, return when queued/written per queue rules (no RX wait).
- Optional **Raw Payload** (hex/raw) for control bytes (e.g. Ctrl-C); no automatic line ending.
- Shares the same per-Target FIFO as Exec.

## Concurrency and mode

- One FIFO queue per Target for Agent Exec/Send.
- Operator UI input **barges in** (prioritized TX); in-flight Exec continues capturing RX and may be disturbed.
- CRT Mode: Exec/Send fail clearly (Operator must switch to Bridge via UI).
- Switching to CRT while Exec is in flight: **abort** Exec immediately (`aborted: true`, optional partial `output`), then release ports.

## Error handling

| Situation | Result |
|-----------|--------|
| CRT Mode exec/send | `ok: false`, instruct Bridge Mode |
| Serial open failure | Cannot enter Bridge; status/UI error |
| Exec > 60s | `timed_out: true` + captured output |
| Prompt hit before idle | Success completion |
| CRT during Exec | `aborted: true` + optional partial output |
| Output > 32KiB | Trailing window + `truncated: true` |
| Bad/missing token (non-loopback) | HTTP 401 |
| Remote `/api/mode` | Rejected |
| Remote Setup secrets / Rotate | Rejected (no plaintext token) |
| Invalid Target Name / duplicate | Reject save; keep prior config |
| Invalid raw/hex | `ok: false`, no TX |
| Corrupt config file | Fall back to env/defaults; warn in status/UI |

## Security notes

- Binding `0.0.0.0` makes the Hub LAN-reachable; Token on MCP and non-loopback send is mandatory for MVP.
- Token never embedded in static frontend assets; Setup Page reveals secrets only on loopback.
- Raw Send can inject control characters; document as full console power.

## Testing

1. ExecEngine unit tests: idle, literal/regex prompt, timeout, truncate, ANSI strip (fake serial/clock).
2. Queue tests: FIFO, Operator barge-in, abort on CRT.
3. Auth tests: loopback exemption; non-loopback send/MCP require Bearer; mode remote rejected.
4. Config tests: slot migrate from legacy `ports`; name/title validation; env Slot aliases; UI persist survives restart.
5. Token tests: first-boot generate; env mirror + override; Rotate + env warning; secrets not in JSON.
6. Setup Page tests: loopback shows token/snippet; non-loopback hides secrets; `/setup` does not collide with `/mcp`.
7. Smoke: MCP exec against fake PortWorker in Bridge; failure in CRT.

## Retirement / docs

- Remove from main path: `send.py`, `read.py`, `bridge.py`, `gui_app.py`.
- README: start Hub, first-boot token / Setup Page, Cursor MCP URL, Port Binding + Target Name, Bridge vs CRT, raw Send warning.
- gitignore `serial_bridge.token` (and document `SERIAL_BRIDGE_TOKEN_FILE`).

## Deferred

- stdio MCP thin proxy.
- `serial_tail` tool.
- Adding/removing Target Slots beyond the fixed two.

## ADR index

- 0001 Shared Hub for UI and MCP
- 0002 Dual MCP access with token (stdio deferred in practice)
- 0003 Exec idle + optional prompt
- 0004 MCP status readonly for mode
- 0005 MVP tools: exec, status, send
- 0006 Abort Exec on CRT switch
- 0007 Token on MCP and write APIs
- 0008 Retire send/read CLI
- 0009 Loopback exemption and mode lock
- 0010 Exec output 32KiB cap
- 0011 Single entrypoint app.py
- 0012 Raw/hex on Send only
- 0013 Operator barge-in
- 0014 Prompt literal or regex
- 0015 Bearer token header
- 0016 Configurable Target ports (extended by 0020 for names/titles)
- 0017 Port Binding UI when free
- 0018 Operator-only port discovery
- 0019 Render SGR in UI; plain logs
- 0020 Configurable Target Name and Display Title (two slots)
- 0021 Access Token secrets file, env override, and Rotate
- 0022 Setup Page; loopback-only secrets
