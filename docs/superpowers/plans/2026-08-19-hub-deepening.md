# Hub deepening — ExecSession + Hub internals

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deepen Exec lifecycle into one ExecSession module, then split Hub authority into deep internals (AgentTrace, Transcript, ModeTransition, SlotPolicy) while keeping a single Hub facade (ADR 0001).

**Architecture:** Hub remains the in-process authority for UI and MCP adapters. New deep modules sit behind Hub (and ExecSession behind PortWorker). No MCP tool shape changes. No Ground Station UI redesign.

**Tech Stack:** Python 3, existing `serial_bridge` package, unittest suite under `tests/`.

**Tickets:** `.scratch/serial-bridge-mcp/issues/01`–`06`

---

## Global Constraints

- Keep one Hub facade; UI and MCP remain adapters (ADR 0001).
- Do not change MCP `serial_exec` / `serial_send` / `serial_status` return shapes (ADR 0005 and related).
- Do not change Access Token / auth behaviour.
- Do not introduce a bundler or rewrite Ground Station UI in this plan.
- Prefer domain vocabulary from `CONTEXT.md`: Hub, Target, Exec, Agent Trace, Bridge Mode, CRT Mode, Live Directory, Port Binding, Target Slot.
- Architecture vocabulary when documenting seams: module, interface, depth, seam, adapter, leverage, locality — not “service/API/boundary” for those concepts.
- Each task: TDD where behaviour changes; run focused tests while iterating; full suite before commit.
- Commit after each task with a message focused on why.
- Work only in worktree `D:\SourceCode\serial_bridge\.worktrees\serial-bridge-mcp` on branch `feature/serial-bridge-mcp`.

---

## Task 1: ExecSession owns happy-path lifecycle

**Ticket:** `.scratch/serial-bridge-mcp/issues/01-execsession-happy-path.md`

**Blocked by:** None

**What to build:** When an Agent Exec completes normally (idle, prompt, or timeout), `exec_result` and Agent Trace start/end come from one ExecSession module; PortWorker no longer owns the happy-path completion triple.

### Steps

- [ ] Write failing tests that drive happy-path Exec through an ExecSession-shaped seam (result + supervision start/end), covering idle/prompt/timeout ended_by as already tested today.
- [ ] Introduce ExecSession (or deepen ExecEngine) so happy-path run records start, executes, and records end with truncated/ok from `exec_result` — PortWorker only invokes the session.
- [ ] Migrate or rewrite existing worker happy-path lifecycle assertions to the new seam; keep Hub `record_exec_*` callable from the session for this task (AgentTrace extract is Task 3).
- [ ] Run focused tests, then full suite; commit.

### Acceptance

- Happy-path Exec returns correct `exec_result`.
- Agent Trace still records start/end for successful Exec.
- PortWorker does not maintain a happy-path completion triple.
- Related Exec / agent_log tests green.

---

## Task 2: ExecSession owns error/abort + one clock/bytes rule

**Ticket:** `.scratch/serial-bridge-mcp/issues/02-execsession-error-clock-bytes.md`

**Blocked by:** Task 1

**What to build:** Error, abort, and missing-completion paths plus a single clock and one bytes-vs-truncated rule live in ExecSession.

### Steps

- [ ] Write failing tests for exception / incomplete / abort end records and for bytes vs truncated divergence at the ExecSession seam; assert one clock source for elapsed_ms.
- [ ] Move remaining PortWorker Exec lifecycle glue into ExecSession; eliminate duplicate `time.monotonic()` bookkeeping outside the session’s clock.
- [ ] Ensure regression formerly in worker tests lives at ExecSession; run suite; commit.

### Acceptance

- Error/abort/incomplete paths end Agent Trace correctly.
- Single clock for elapsed_ms.
- bytes vs truncated covered at ExecSession.
- Related suite green.

---

## Task 3: Hub delegates Agent Trace to deep AgentTrace

**Ticket:** `.scratch/serial-bridge-mcp/issues/03-hub-agent-trace.md`

**Blocked by:** Task 2

**What to build:** Ring buffer, exec start/end recording, and WS exec emit contract live in AgentTrace; Hub delegates; Operator Trace unchanged.

### Steps

- [ ] Write failing tests that construct/use AgentTrace for start/end/ring/get_agent_log (or extend existing agent_log tests to the new module while Hub still facades).
- [ ] Extract AgentTrace; Hub holds and delegates; ExecSession (or Hub) calls AgentTrace for supervision records.
- [ ] Confirm WS exec events still emit via existing Hub.emit path as today.
- [ ] Run suite; commit.

### Acceptance

- `get_agent_log` and exec WS events unchanged in behaviour.
- Hub does not inline ring/start/end bodies.
- agent_log tests green via Hub or AgentTrace.

---

## Task 4: Hub delegates transcript to deep Transcript

**Ticket:** `.scratch/serial-bridge-mcp/issues/04-hub-transcript.md`

**Blocked by:** None (SDD order: after Task 3)

**What to build:** append_log, session log paths, and get_tail go through Transcript; Hub facade; console and Live Directory logs unchanged.

### Steps

- [ ] Write failing tests for Transcript behaviour (append + tail + session path assignment hooks as needed).
- [ ] Extract Transcript; Hub delegates append_log / get_tail / session log assignment helpers used by mode transitions.
- [ ] Run related Hub tests + full suite; commit.

### Acceptance

- Operator append/tail behaviour unchanged.
- Session logs under Live Directory still created as before.
- Hub delegates transcript work.

---

## Task 5: Hub delegates Bridge/CRT to deep ModeTransition

**Ticket:** `.scratch/serial-bridge-mcp/issues/05-hub-mode-transition.md`

**Blocked by:** Task 4

**What to build:** start_bridge / stop_bridge (workers, ports, session log assignment via Transcript) live in ModeTransition; Hub facade.

### Steps

- [ ] Write failing tests targeting ModeTransition (or extend Hub mode tests to assert delegation without behaviour change).
- [ ] Extract ModeTransition; Hub.start_bridge / stop_bridge delegate; session logs via Transcript.
- [ ] Run suite; commit.

### Acceptance

- Bridge/CRT switch behaviour unchanged.
- Session logs assigned on Bridge entry.
- Mode-related tests green.

---

## Task 6: SlotPolicy owns Target Slot mutation rules

**Ticket:** `.scratch/serial-bridge-mcp/issues/06-slot-policy.md`

**Blocked by:** None (SDD order: after Task 5)

**What to build:** Title-only, live_dir, and Bridge rejection of binding edits decided by SlotPolicy; Hub asks then applies.

### Steps

- [ ] Write failing tests for SlotPolicy decisions (allow/deny + title-only vs full apply implications) matching current Hub.update_slots rules.
- [ ] Extract SlotPolicy beside Config; Hub.update_slots uses it with current mode as input.
- [ ] Run config/hub binding tests + full suite; commit.

### Acceptance

- CRT vs Bridge binding rules unchanged.
- Title-only and live_dir rules unchanged.
- Hub uses SlotPolicy.

---

## Execution order (SDD)

Despite tickets 01/04/06 having no blockers, implement **serially**: 1 → 2 → 3 → 4 → 5 → 6 (no parallel implementers).
