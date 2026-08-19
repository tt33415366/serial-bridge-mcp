# Ground Station Operator UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reinvent the Operator Bridge console as Ground Station and surface Agent Exec lifecycle so an Operator can supervise Agents at a glance.

**Architecture:** Hub observes Exec via `on_done` and emits `{"type":"exec","phase":"start"|"end",...}` on the Operator WebSocket, keeping an in-memory ring served by `GET /api/agent_log`. The static UI becomes Ground Station chrome with orthogonal Target/speaker grammar, Exec capture brackets + holder lamps, and a middle Agent Trace spine hydrated from the ring.

**Tech Stack:** Python 3 / FastAPI Hub, unittest, static HTML/CSS/JS (no bundler), WebSocket Operator channel.

**Spec:** `docs/superpowers/specs/2026-08-19-ground-station-ui-design.md`  
**Tickets:** `.scratch/ground-station-ui/issues/`  
**Worktree:** `.worktrees/serial-bridge-mcp` on `feature/serial-bridge-mcp`

## Global Constraints

- MCP `exec_result()` / Agent-facing Exec return shape **unchanged**
- No new MCP tools; Exec observation is Operator WS + `GET /api/agent_log` only
- Agent log ring is **in-memory only** (~50 Exec records); Hub restart clears it; **never** merge into `status()` / `bridge_status.json`
- Holder lamp driven by Exec start/end for that Target — **not** `status().busy`
- Color grammar: Target = column structure color; speaker = Agent purple / Operator gold / device neutral / system muted
- `ended_by` is exactly one of: `idle` | `prompt` | `timeout` | `abort` | `error`
- Exec WS payloads match:

```jsonc
{"type":"exec","phase":"start","id":17,"target":"linux","cmd":"…","prompt":null,"ts":"HH:MM:SS.mmm"}
{"type":"exec","phase":"end","id":17,"target":"linux","ended_by":"idle","ms":1240,"bytes":3174,"truncated":false,"ok":true}
```

- SETUP is a plain same-row text link (not a bordered button)
- Motion budget only: page rise, running-Exec scan + holder blink, mode knob slide
- No React/bundler; stay on `static/index.html`, `style.css`, `app.js`
- Glossary: Hub, Target, Target Name, Operator, Agent, Exec, Send, Bridge Mode, CRT Mode (`CONTEXT.md`)
- Commits: English messages; code/comments English
- Do not dispatch parallel implementers; sequential Tasks 1→4

## File map

| File | Responsibility |
|------|----------------|
| `serial_bridge/hub/exec.py` | Call `on_done(ended_by, captured_bytes)` once per completion path |
| `serial_bridge/hub/worker.py` | Emit exec start before execute; wire on_done → Hub |
| `serial_bridge/hub/core.py` | Exec id counter, agent_log ring, `record_exec_*`, `get_agent_log()` |
| `serial_bridge/operator.py` | `GET /api/agent_log` |
| `static/index.html` | Ground Station DOM: rail, tubes, spine slot, holders |
| `static/style.css` | Michroma/Martian Mono, palette, layout, capture, spine |
| `static/app.js` | Line grammar, capture, holder, spine, agent_log hydrate |
| `static/setup.html` | Fonts/variables only |
| `tests/test_exec.py` | on_done paths |
| `tests/test_hub.py` or new `tests/test_agent_log.py` | ring + emit + REST |

---

### Task 1: Emit Exec lifecycle to the Operator

**Files:**
- Modify: `serial_bridge/hub/exec.py`
- Modify: `serial_bridge/hub/worker.py`
- Modify: `serial_bridge/hub/core.py`
- Modify: `serial_bridge/operator.py`
- Modify: `tests/test_exec.py`
- Create or modify: `tests/test_agent_log.py` (preferred new file) and wire through existing Hub/operator test patterns in `tests/test_hub.py` / `tests/test_app.py` if needed for HTTP

**Interfaces:**
- Consumes: existing `ExecEngine.execute`, `PortWorker` exec path, `Hub.emit`, Operator route registration
- Produces:
  - `on_done: Callable[[str, int], None] | None` on `execute(..., on_done=...)` where args are `(ended_by, captured_bytes)` and `captured_bytes` is `len(captured)` raw RX bytearray before strip/cap
  - `Hub.record_exec_start(target, cmd, prompt) -> int` returns monotonic id; emits start; appends ring running entry
  - `Hub.record_exec_end(id, target, ended_by, ms, bytes, truncated, ok) -> None` emits end; updates ring
  - `Hub.get_agent_log() -> list[dict]` newest-first, max 50 Exec records (Send not stored server-side)
  - `GET /api/agent_log` → `{"ok": true, "entries": [...]}` with Operator access dependency matching `/api/ports`

**Ticket acceptance (must all pass):**
- Paired start/end WS messages with stable id
- Five `ended_by` paths each fire `on_done` exactly once
- End payload has ms, bytes, truncated, ok
- GET agent_log newest-first; not in status/bridge_status.json
- MCP exec_result unchanged
- Tests for all five end reasons

- [ ] **Step 1: Write failing tests for `on_done`**

Extend `tests/test_exec.py` helper to accept `on_done` and assert:

```python
def test_on_done_idle(self):
    calls = []
    result, serial, clock = execute(
        [(0.0, b"show\r\n"), (0.2, b"answer\r\n")],
        on_done=lambda ended_by, nbytes: calls.append((ended_by, nbytes)),
    )
    self.assertEqual([("idle", len(b"show\r\nanswer\r\n"))], calls)  # adjust nbytes to actual captured chunks
    self.assertTrue(result["ok"])

# similarly: prompt → "prompt"; timeout → "timeout"; abort → "abort";
# invalid prompt regex before write → "error" with nbytes 0
# write_if_allowed False → "abort" with nbytes 0
```

Update `execute()` helper to pass `on_done` through to `ExecEngine.execute`.

- [ ] **Step 2: Run tests — expect FAIL** (missing `on_done` kwarg / not called)

Run: `python -m pytest tests/test_exec.py -v`  
Expected: FAIL on new tests.

- [ ] **Step 3: Implement `on_done` in ExecEngine**

Add optional `on_done: Callable[[str, int], None] | None = None`.

Helper pattern — call exactly once before every return:

```python
def _finish(self, on_done, ended_by: str, captured: bytearray, result: dict) -> dict:
    if on_done is not None:
        on_done(ended_by, len(captured))
    return result
```

Map returns:
- invalid regex → `error`, empty captured
- `write_if_allowed` false → `abort`, empty
- `aborted.is_set` → `abort`
- total timeout → `timeout`
- prompt match → `prompt`
- idle gap → `idle`

Do not change `exec_result(...)` field set.

- [ ] **Step 4: GREEN for on_done tests**

Run: `python -m pytest tests/test_exec.py -v`  
Expected: PASS.

- [ ] **Step 5: Hub ring + worker emit + REST — failing tests first**

In `tests/test_agent_log.py` (new):

```python
def test_record_exec_round_trip_newest_first(self):
    hub = Hub(config=...)  # follow existing Hub test fixtures
    i1 = hub.record_exec_start("linux", "one", None)
    hub.record_exec_end(i1, "linux", "idle", 100, 10, False, True)
    i2 = hub.record_exec_start("rtos", "two", None)
    hub.record_exec_end(i2, "rtos", "prompt", 50, 5, False, True)
    entries = hub.get_agent_log()
    self.assertEqual(i2, entries[0]["id"])
    self.assertEqual("end", entries[0]["phase"])  # or sealed shape documented below
    self.assertNotIn("agent_log", hub.status())

def test_api_agent_log_loopback(self):
    # Use existing FastAPI TestClient pattern from tests/test_app.py / test_setup.py
    # GET /api/agent_log returns {"ok": True, "entries": ...}
```

Ring entry shape (locked for Tasks 3–4):

```python
# after start (still running):
{"id": int, "phase": "start", "target": str, "cmd": str, "prompt": str|None, "ts": str}
# after end (replace/update same id):
{"id": int, "phase": "end", "target": str, "cmd": str, "prompt": str|None, "ts": str,
 "ended_by": str, "ms": int, "bytes": int, "truncated": bool, "ok": bool}
```

Keep at most 50 entries (drop oldest id when exceeding).

- [ ] **Step 6: Implement Hub + PortWorker + route**

`Hub`:
- `_exec_id` counter under lock
- `_agent_log: deque` maxlen 50
- `record_exec_start` / `record_exec_end` / `get_agent_log`
- emit WS messages matching Global Constraints payloads (start uses `ts()` from `hub.text`)

`PortWorker` around `ExecEngine.execute`:
1. `exec_id = hub.record_exec_start(...)` before execute (or immediately when on_tx fires — prefer **before** `execute` returns into the engine, right after dequeue, so start is visible even if write aborts; if write aborts, still emit end via on_done)
2. Pass `on_done` that computes `ms` from monotonic times and calls `hub.record_exec_end`

`operator.py`:
```python
@app.get("/api/agent_log", dependencies=[Depends(_require_operator_access)])
async def api_agent_log() -> dict[str, Any]:
    return {"ok": True, "entries": await offload(_get_hub().get_agent_log)}
```

- [ ] **Step 7: GREEN full focused suite**

Run: `python -m pytest tests/test_exec.py tests/test_agent_log.py tests/test_hub.py tests/test_mcp.py -v`  
Expected: PASS; MCP exec assertions unchanged.

- [ ] **Step 8: Commit**

```bash
git add serial_bridge/hub/exec.py serial_bridge/hub/worker.py serial_bridge/hub/core.py serial_bridge/operator.py tests/test_exec.py tests/test_agent_log.py
git commit -m "Emit Exec lifecycle events and agent_log for Operator supervision."
```

---

### Task 2: Ground Station shell and speaker grammar

**Files:**
- Modify: `static/index.html`
- Modify: `static/style.css`
- Modify: `static/app.js`
- Modify: `static/setup.html` (fonts + CSS variables only)

**Interfaces:**
- Consumes: existing WS `status` / `line` / mode / bindings APIs (unchanged)
- Produces: DOM ids that Tasks 3–4 will use:
  - `#term-slot0` / `#term-slot1` remain the scroll containers (or `.screen` wrappers — keep `term-slot0`/`term-slot1` ids)
  - `#holder-slot0` / `#holder-slot1` elements present (can stay `IDLE` / unused until Task 3)
  - `#agent-spine` / `#spine-body` / `#spine-tally` present as empty shells for Task 4
  - Binding strip: `#binding-strip` visible in Bridge; `#binding-form` expanded fields in CRT (existing form id kept)

**Ticket acceptance:**
- Ground Station fonts/palette/rail/header/mode knob
- SETUP same-row plain link
- Bindings strip vs CRT expand
- Speaker grammar without Target colors for speaker
- Send/history/clear/WS still work
- Setup page font/variable align only

- [ ] **Step 1: Restructure `index.html` chrome**

Implement Ground Station skeleton matching mockup A:
- `.shell` → `.rail` + `.main`
- Header: title, `.mode` knob, `.readout` (`#status-pill` can move into readout), plain `<a class="setup-link" href="/setup">Setup</a>`
- `#binding-strip` read-only summary; keep `#binding-form` for CRT edit (show/hide via JS from mode)
- `.field` with two `.tube` panes + empty `#agent-spine` between them
- Each pane: `#holder-slotN`, `#term-slotN`, composer
- Footer unchanged in behavior

Preserve all ids `app.js` already queries (`btn-bridge`, `binding-slot0-title`, composers, etc.) or update `app.js` in the same task to match renamed ids — prefer preserving ids.

- [ ] **Step 2: Replace `style.css` with Ground Station tokens**

Google fonts: Michroma + Martian Mono.  
CSS variables from spec/mockup: `--void`, `--deep`, `--panel`, `--linux`, `--rtos`, `--agent`, `--operator`, `--device`, etc.  
Keep ANSI `--ansi-0`…`--ansi-15`.  
Line classes: `.ln.agent|.op|.dev|.sys` with left edge marks.  
≤960px: stack panes; spine full-width under (even if empty).  
Do **not** implement capture/spine visual polish beyond empty column placeholder.

- [ ] **Step 3: Update `appendLine` speaker grammar in `app.js`**

```javascript
// direction <<< → .ln.dev
// direction >>> + who agent → .ln.agent, prefix "◆ agent"
// direction >>> + else → .ln.op, prefix "▲ you"
// direction --- → .ln.sys
```

Keep `AnsiRender.renderAnsi` on the body.  
Toggle binding strip vs form from `applyStatus` mode.  
Do not wire exec events yet.

- [ ] **Step 4: Align `setup.html` fonts/variables** only (no spine).

- [ ] **Step 5: Manual smoke** — open UI (or rely on existing `tests/test_app.py` static route tests). Run: `python -m pytest tests/test_app.py tests/test_command_history.py -v`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add static/index.html static/style.css static/app.js static/setup.html
git commit -m "Restyle Operator console as Ground Station shell."
```

---

### Task 3: Exec capture brackets and Target holder lamp

**Files:**
- Modify: `static/app.js`
- Modify: `static/style.css` (capture + holder styles if not already)

**Interfaces:**
- Consumes: WS `type:exec` start/end from Task 1; `#holder-slotN`; term containers from Task 2
- Produces: per-Target open capture state; holder text `IDLE` | `AGENT EXEC`

**Ticket acceptance:**
- Start opens capture on matching pane
- Only `<<<` during open Exec enter capture; Operator lines outside
- End seals with ms, bytes, ended_by, capped if truncated
- Abort wording; barge-in outside capture
- Holder from Exec events only
- No invented bracket for Execs that started before connect

- [ ] **Step 1: Handle `exec` in `ws.onmessage`**

```javascript
const openCaptures = {}; // target -> { id, el }
function onExecStart(msg) {
  const slot = targetToSlot[msg.target];
  if (!slot) return;
  const capture = document.createElement("div");
  capture.className = "capture";
  capture.dataset.execId = String(msg.id);
  terms[slot].appendChild(capture);
  openCaptures[msg.target] = { id: msg.id, el: capture };
  setHolder(slot, true);
}
function onExecEnd(msg) {
  const open = openCaptures[msg.target];
  if (open && open.id === msg.id) {
    const foot = document.createElement("div");
    foot.className = "cap-foot";
    foot.textContent = sealCopy(msg); // ms, bytes, ended_by, capped
    open.el.appendChild(foot);
    delete openCaptures[msg.target];
  }
  setHolder(slotFor(msg.target), false);
}
```

- [ ] **Step 2: Route `<<<` into open capture**

In `appendLine`, if `direction === "<<<"` and `openCaptures[target]`, append the row into `openCaptures[target].el`; else into `terms[slot]`. Operator/agent/sys never enter capture.

- [ ] **Step 3: Style `.capture` / `.holder.agent`** per Ground Station (scan/blink for holder when agent).

- [ ] **Step 4: Commit**

```bash
git add static/app.js static/style.css
git commit -m "Bracket Exec captures and drive Target holder lamps."
```

---

### Task 4: Agent Trace spine

**Files:**
- Modify: `static/app.js`
- Modify: `static/style.css`
- Modify: `static/index.html` only if spine markup incomplete from Task 2

**Interfaces:**
- Consumes: `GET /api/agent_log`, WS `exec` events, agent `>>>` lines
- Produces: spine nodes newest-first; tally; rehydrate on connect/reconnect

**Ticket acceptance:**
- Exec nodes running→sealed from exec events
- Send nodes from agent `>>>` only
- Newest-first + running scan
- Footer tally client-side
- Load + WS reconnect replace buffer from GET
- ≤960px spine under panes

- [ ] **Step 1: Spine model + render**

Keep `spineEntries = []` (exec + send). On exec start: unshift running node; on end: update same id. On agent `>>>`: unshift send node (`fire-and-forget`). Re-render `#spine-body` and `#spine-tally`.

Tally: exec count, send count, aborted count, capped count, median ms of sealed execs.

- [ ] **Step 2: Hydrate**

```javascript
async function hydrateAgentLog() {
  const res = await fetch("/api/agent_log");
  const data = await res.json();
  if (!data.ok) return;
  spineEntries = entriesFromAgentLog(data.entries); // map ring → UI nodes
  // also set holders for any phase===start without end
  renderSpine();
}
```

Call on initial load and on every successful WS `onopen` (reconnect), replacing the client buffer.

- [ ] **Step 3: Responsive CSS** — spine full-width under panes at ≤960px.

- [ ] **Step 4: Run regression**

Run: `python -m pytest -v`  
Expected: PASS (full suite).

- [ ] **Step 5: Commit**

```bash
git add static/app.js static/style.css static/index.html
git commit -m "Add Agent Trace spine with agent_log hydration."
```

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| Exec WS start/end + ended_by | 1 |
| Agent log ring + GET /api/agent_log | 1 |
| MCP unchanged / not in status | 1 |
| Ground Station chrome + fonts | 2 |
| Speaker/Target grammar | 2 |
| SETUP plain link | 2 |
| Bindings strip / CRT expand | 2 |
| Capture brackets + seal | 3 |
| Holder lamp | 3 |
| Agent Trace spine + tally + hydrate | 4 |
| Motion budget / no phosphor | 2–4 (CSS only those motions) |
