# Ground Station Operator UI Design

Date: 2026-08-19  
Status: Approved for implementation planning  
Glossary: [`CONTEXT.md`](../../../CONTEXT.md)  
Parent: [`2026-08-18-serial-bridge-mcp-design.md`](./2026-08-18-serial-bridge-mcp-design.md)

## Problem

The Operator console is a flat dark “dev tool” layout: header, banner, bindings, dual panes, and footer all share the same hairline + muted-uppercase treatment, so the dual Target streams do not dominate the viewport. More importantly, the Operator’s primary job is **supervising an Agent**, but the UI only distinguishes Agent vs Operator via weak text colors, has no “Agent is executing on this Target” lamp (and `status().busy` cannot provide one, because it mixes Agent and Operator queues), and never surfaces Exec lifecycle data (duration, captured bytes, idle vs prompt vs abort vs timeout vs truncated) that already exists inside `ExecEngine` and is returned only to the Agent.

## Goals

- Reinvent the Bridge console visual identity as **Ground Station** (direction A from brainstorming): deep indigo atmosphere, Michroma + Martian Mono, Linux/RTOS as structural column colors, Agent as a non-device purple.
- Make **speaker** and **Target** orthogonal: Target = which column; speaker = chromatic mark inside the column (Agent / Operator / device / system).
- Turn each Agent **Exec** into a visible object: bracket device output in a capture region and seal it with duration, byte count, and end reason.
- Add a dedicated **Agent Trace spine** between the two panes listing this session’s Exec/Send activity for at-a-glance supervision.
- Emit Exec lifecycle over the existing Operator WebSocket (and a small REST backfill) without changing MCP tool return shapes.

## Non-goals

- Changing MCP tool contracts or `exec_result()` fields Agents already consume.
- New MCP tools, traffic sparklines, baud meters, or cross-session durable Agent history (in-memory ring only; Hub restart clears it).
- Turning Setup into a modal; Setup stays `/setup` and only aligns fonts/CSS variables.
- Introducing React or a bundler; remain static `index.html` / `style.css` / `app.js`.
- Changing session log file format, Command History semantics, or Port Binding persistence rules.
- Phosphor/CRT effects, paper textures, custom cursors, particle motion, or scroll-triggered animation.

## Decisions (locked)

| Topic | Choice |
|--------|--------|
| Visual direction | Ground Station (A), not Lab Notebook or Phosphor Rack |
| Supervision scope | Reskin + layout + new visual features fed by Exec observation events |
| Color grammar | Target = column structure color; speaker = Agent purple / Operator gold / device neutral / system muted |
| Exec observation | WS `{"type":"exec","phase":"start"|"end",...}` via `on_done` callback; MCP `exec_result` unchanged |
| Send in spine | Derived from existing `line` (`who=agent`, `direction=>>>`); no new backend event |
| Holder lamp | Driven by open Exec start/end for that Target, **not** `status().busy` (busy conflates Agent and Operator queues) |
| Agent log persistence | Hub in-memory ring (~50 Exec records); `GET /api/agent_log`; not written into `bridge_status.json` |
| Bindings chrome | Bridge: one-line read-only strip; CRT: expand existing editable form (titles, COM, baud, Live Directory) |
| Setup control | Plain text link in the header (not a bordered button); layout must keep it on the same header row |
| Motion budget | Page rise, running-Exec scan + holder blink, mode knob slide only |

## Architecture

```text
ExecEngine.execute(..., on_done)
  └─ PortWorker wraps on_tx/on_rx + on_done
       └─ Hub.emit({type:"exec", phase, id, target, ...})
       └─ Hub.agent_log ring append (end records + running start)

Operator UI
  WS line          → transcript + (agent >>> → spine SEND node)
  WS exec start/end → capture bracket + holder + spine EXEC node
  GET /api/agent_log → hydrate spine after refresh
```

### Exec WebSocket contract

```jsonc
{"type":"exec","phase":"start","id":17,"target":"linux","cmd":"cat /proc/meminfo","prompt":null,"ts":"20:38:42.118"}
{"type":"exec","phase":"end","id":17,"target":"linux","ended_by":"idle",
 "ms":1240,"bytes":3174,"truncated":false,"ok":true}
```

- `ended_by`: `idle` | `prompt` | `timeout` | `abort` | `error` — one value per existing return branch in `ExecEngine.execute`.
- Pure observation: no change to write ordering, barge-in, abort, or MCP responses.
- Implementation: add `on_done(ended_by, captured_bytes)` alongside existing `on_tx` / `on_rx` / `service_operator`; `PortWorker` translates to Hub emit + ring store.

### Agent log REST

- `GET /api/agent_log` (loopback Operator auth, same class as other Operator reads) returns the ring newest-first.
- Deliberately **not** merged into `status()` so `_write_bridge_status()` does not grow with history.

### Transcript grammar

- Row DOM: `.ln.{agent|op|dev|sys}` with `.t` timestamp and `.b` body; Agent/Operator rows carry a 2px left edge mark.
- Prefix glyphs (`◆ agent`, `▲ you`) are display-only, derived from `direction` + `who`.
- On `exec` start: open `.capture` in that Target’s pane; subsequent `<<<` device lines append inside it until `exec` end, which writes a seal line (`captured … · … KiB · closed on idle|prompt|…`, plus `· capped` when `truncated`).
- Operator barge-in lines during an open capture stay in the pane but **outside** `.capture`; the spine node seals as aborted when `ended_by=abort`.

### Agent Trace spine

- Fixed middle column (~208px) between the two tubes on desktop.
- Nodes: Exec from `exec` events (running → sealed); Send from agent `>>>` lines (no progress bar; `fire-and-forget`).
- Newest first; running node shows scan animation.
- Footer tally (exec count, send count, aborted/capped, median ms) computed in the browser from the hydrated buffer.

### Layout chrome

- Left rail: brand sigil + vertical wordmark + WS lamp.
- Header: title, Bridge/CRT mode knob, Hub readout, plain `SETUP` link (same row; no auto-wrapped lone link).
- Bindings strip vs expanded CRT form as above.
- Footer: Live Directory + session log basenames + Clear (behavior unchanged).

### Visual system

- Fonts: Michroma (display), Martian Mono (body/transcript). Replace Oxanium + IBM Plex Mono on Bridge and Setup.
- Palette tokens from Ground Station mockup (`--void`, `--deep`, `--panel`, `--linux`, `--rtos`, `--agent`, `--operator`, `--device`). Keep the existing 16 ANSI colors for SGR rendering; default device text uses `--device`.
- Responsive ≤960px: spine becomes a full-width band under the stacked panes; rail collapses to a top strip. Desktop Operator use is the priority.

## Error handling

| Situation | Result |
|-----------|--------|
| Page refresh mid-Exec | `GET /api/agent_log` may show a start without end; holder follows subsequent WS; capture bracket only for Execs that start after connect |
| WS drop / retry | Existing reconnect; on next successful connect, re-fetch `/api/agent_log` and replace the spine buffer so nodes match Hub memory |
| Unknown `ended_by` | Treat as `error` in seal copy; do not crash render |
| Agent log ring full | Drop oldest Exec records |

## Testing

1. `ExecEngine`: `on_done` invoked exactly once on each completion path (`idle`, `prompt`, `timeout`, `abort`, `error`) with correct `ended_by` and byte count.
2. Hub/Worker: start and end `exec` messages emitted on the Operator WS with stable `id` per Exec; MCP `exec_result` shape unchanged.
3. `GET /api/agent_log` returns newest-first ring contents; excluded from `bridge_status.json` / `status()` payload size concerns.
4. UI (manual or thin JS-facing checks): capture brackets only `<<<` during open Exec; Operator lines during Exec do not enter capture; holder toggles on start/end; spine lists Exec + agent Send; Setup remains a same-row text link.

## File boundary

| Area | Files |
|------|--------|
| Exec observation | `serial_bridge/hub/exec.py`, `worker.py`, `core.py` |
| REST | `serial_bridge/operator.py` (`GET /api/agent_log`) |
| UI | `static/index.html`, `static/style.css`, `static/app.js`; Setup fonts/variables only |
| Tests | `tests/test_exec.py` plus agent_log / WS exec coverage |

## Deferred

- Persisting Agent Trace across Hub restarts.
- Filtering/search inside the spine.
- Highlighting the capture region in the on-disk session log (UI-only brackets for MVP).
