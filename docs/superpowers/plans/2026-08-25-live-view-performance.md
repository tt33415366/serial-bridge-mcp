# Live View Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the Operator reduce live-pane DOM depth on demand and pause materializing incoming transcript lines while reading history, without changing complete session logs or the Hub protocol.

**Architecture:** Keep the existing WebSocket and `appendLine` path while a pane follows its live tail. Add one shared Live View Budget for both panes, then add per-pane Follow state that buffers a bounded recovery view while detached from the tail. Reuse the existing O(1)-style oldest-row trim path and Node-backed UI test harness.

**Tech Stack:** Plain HTML/CSS/JavaScript, Python `unittest`/pytest wrapper, Node fake DOM scenarios.

## Global Constraints

- Do not change Hub, WebSocket, transcript persistence, or session-log behavior.
- While Follow is active, every incoming line still uses the existing `appendLine` and ANSI-render path.
- Follow is independent per Target pane and detaches when the pane is more than 32 px from its live tail.
- Transcript Gap copy is exactly `— {space-grouped count} lines in session log, not in this view —`.
- A Transcript Gap counts only rows actually evicted from the bounded detached buffers (retained/replayed rows are not counted). Adjacent Transcript Gaps merge if one is ever inserted right after another, though normal flow never produces that adjacency (the retained tail + writes buffers are bounded well under the smallest Live View Budget, so a Gap and its own replay never get separated by budget trimming); the merge path is a defensive guard, not currently reachable.
- Live View Budget is shared by both panes, offers exactly 500, 5k, and 75k, defaults to 75k, persists in `localStorage`, and tightening it immediately trims both panes.
- Tightening Live View Budget silently drops oldest materialized rows and does not create a Transcript Gap.
- A Transcript Gap counts as one materialized line for Live View Budget.
- Preserve the existing industrial Ground Station visual language; the budget control is a three-stop `depth` instrument in the footer immediately left of Clear.
- Do not add dependencies or speculative virtualization/flood coalescing.

---

### Task 1: Live View Budget depth instrument

**Files:**
- Modify: `static/index.html`
- Modify: `static/style.css`
- Modify: `static/app.js`
- Test: `tests/test_ground_station_exec_ui.py`

**Interfaces:**
- Produces: `liveViewBudget: number`, initialized from local storage key `serial-bridge-live-view-budget`.
- Produces: `setLiveViewBudget(value)` which accepts only `500`, `5000`, or `75000`, persists the value, updates the instrument, and trims both panes.
- Changes: `trimTerm(el)` uses `liveViewBudget` instead of the fixed `MAX_TERM_LINES`.

- [x] **Step 1: Write failing UI scenarios**

Add focused scenarios proving:
1. invalid/missing persisted values resolve to 75k and the `75k` stop is active;
2. selecting `500` stores `500`, marks that stop active, and immediately trims both panes to 500;
3. selecting `5k` restores `5000` on next evaluation;
4. existing capture-row accounting and no-rescan trim behavior remain intact.

Extend the fake `localStorage` and element event support only as needed to observe these behaviors.

- [x] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest tests/test_ground_station_exec_ui.py -q`

Expected: new scenarios fail because the depth control and dynamic budget do not exist.

- [x] **Step 3: Implement the minimal depth instrument**

Add footer markup with three buttons carrying exact values `500`, `5000`, and `75000`; accessible group label `Live view depth`; visible labels `depth 500`, `5k`, and `75k`. Style it as a compact three-stop Ground Station instrument using existing variables and typography. In JavaScript, validate persisted values against a fixed allowed set, bind button clicks, update `aria-pressed`/active state, persist changes, and trim both panes immediately.

- [x] **Step 4: Verify GREEN**

Run: `python -m pytest tests/test_ground_station_exec_ui.py -q`

Expected: all focused tests pass with pristine output.

- [x] **Step 5: Run the full suite and commit**

Run: `python -m pytest`

Expected: 244+ tests pass; only the known pre-existing Pydantic warning may remain.

Commit subject: `Add a live view depth instrument.`

---

### Task 2: Per-pane Follow with Transcript Gap recovery

**Files:**
- Modify: `static/style.css`
- Modify: `static/app.js`
- Test: `tests/test_ground_station_exec_ui.py`

**Interfaces:**
- Consumes: `trimTerm(el)` and `liveViewBudget` from Task 1.
- Produces: per-pane state containing `following`, evicted count, and a ring of the last 32 buffered `<<<` lines.
- Produces: `isNearLiveTail(el)` using a 32 px tolerance.
- Produces: Transcript Gap rows with class `ln gap`, a numeric evicted count, and a defensive merge path for an adjacent prior gap.

- [x] **Step 1: Write failing Follow scenarios**

Add focused scenarios proving:
1. each pane independently detaches when its scroll event reports more than 32 px from the tail;
2. detached panes do not append incoming `<<<` rows to the DOM;
3. detached panes retain only the newest 32 `<<<` payloads and count every evicted row;
4. returning to the tail appends one Transcript Gap (only when a row was actually evicted) followed by the retained rows in original order;
5. the exact Gap copy uses space-grouped digits;
6. the Gap counts as one budget row;
7. the other pane keeps following and rendering normally.

Update the fake element geometry so `clientHeight`, `scrollHeight`, and `scrollTop` can model near-tail state without changing unrelated scenarios.

- [x] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest tests/test_ground_station_exec_ui.py -q`

Expected: new scenarios fail because panes always schedule scrolling and never pause materialization.

- [x] **Step 3: Implement minimal Follow state**

Initialize per-pane state as following. On user scroll, compare `scrollHeight - clientHeight - scrollTop` with the 32 px threshold. While detached, route `<<<` lines into a count plus a fixed 32-entry tail rather than `appendLine`. When Follow resumes, append or merge a single Gap, replay the retained tail through the existing line renderer without recursively pausing it, clear buffered state, and resume scheduled tail scrolling. Style Gap rows as subdued telemetry separators consistent with the existing tube.

- [x] **Step 4: Verify GREEN**

Run: `python -m pytest tests/test_ground_station_exec_ui.py -q`

Expected: all focused tests pass with pristine output.

- [x] **Step 5: Run the full suite and commit**

Run: `python -m pytest`

Expected: 244+ tests pass; only the known pre-existing Pydantic warning may remain.

Commit subject: `Pause transcript materialization off tail.`

---

### Task 3: Replay bounded writes while Follow is paused

**Files:**
- Modify: `static/app.js`
- Test: `tests/test_ground_station_exec_ui.py`

**Interfaces:**
- Consumes: per-pane Follow state and recovery flush from Task 2.
- Extends: detached state with at most 200 retained `>>>`/`---` rows.
- Extends: recovery ordering by timestamp across retained writes and the 32-line device tail.

- [x] **Step 1: Write failing replay scenarios**

Add focused scenarios proving:
1. detached panes do not materialize `>>>`/`---` immediately;
2. up to 200 writes/system rows replay when Follow resumes;
3. the 201st retained write evicts the oldest and increments the same Gap count;
4. retained writes and the 32-line device tail replay in ascending timestamp order;
5. Agent Send recording semantics remain unchanged despite delayed materialization;
6. capture and Trace Jump behavior remains valid only for captures still in the materialized view.

- [x] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest tests/test_ground_station_exec_ui.py -q`

Expected: new scenarios fail because detached non-device rows are not buffered or replayed.

- [x] **Step 3: Implement bounded write replay**

Buffer detached `>>>`/`---` rows in a 200-entry queue while preserving their existing side effects exactly once. On overflow, increment the pane's evicted count. On recovery, combine retained writes with the retained device tail, sort stably by timestamp while preserving arrival order for equal/missing timestamps, append the Gap first only if a row was actually evicted, reattach any capture the Gap's own budget trim displaced, then replay combined rows through the existing renderer. Clear all detached buffers afterward.

- [x] **Step 4: Verify GREEN**

Run: `python -m pytest tests/test_ground_station_exec_ui.py -q`

Expected: all focused tests pass with pristine output.

- [x] **Step 5: Run the full suite and commit**

Run: `python -m pytest`

Expected: 244+ tests pass; only the known pre-existing Pydantic warning may remain.

Commit subject: `Replay bounded writes after following resumes.`
