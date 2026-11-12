# Agent Mode Switch, Exec Status, Port State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an Agent switch Bridge/CRT Mode only with Operator permission, and make Exec results and Target status say precisely what happened (Exec Status, Raw Capture, Port State, Shell Readiness).

**Architecture:** Hub stays the single authority. `exec_result` gains a `status`; `PortWorker` gains a `lost` flag and tells the Hub when its port drops; `ModeTransition.start_bridge` stops rolling back and reports per-Target open results; a small `ShellReadiness` tracker plus an Operator-configured Target Prompt feed `shell` in status; `Hub.set_mode_agent` checks permission and busy atomically; MCP gets `serial_set_mode`.

**Tech Stack:** Python 3, FastAPI, FastMCP, pyserial, `unittest` classes run by pytest (`python -m pytest`), vanilla JS in `static/`.

## Global Constraints

- Source of truth for vocabulary: `CONTEXT.md` (Mode Switch Permission, Port State, Shell Readiness, Exec Status, Raw Capture, Target Prompt). Source of truth for the decision: `docs/adr/0033-agent-mode-switch-permission.md`.
- Existing Operator endpoints (`/api/mode`, `/api/bindings`, `/api/ports`, `/ws` mode messages) stay loopback-only. Port discovery and Port Binding edits stay Operator-only (ADR 0017, 0018). No MCP tool may list COM ports or change a Port Binding.
- Mode Switch Permission: in memory only, default off after every Hub start, checked once when a request starts. Revoking never undoes or interrupts a switch already accepted.
- Agent mode switch is refused while any Target `is_busy`; the refusal returns `busy_targets` and nothing is queued. Permission check, busy check and "switch started" are one atomic step under `Hub._transition_lock` plus `Hub._state_lock`.
- Exec Status values, exactly: `completed`, `quiet`, `timeout`, `disconnected`, `aborted`, `error`. `ended_by` stays in Agent Trace as detail.
  - `completed` means prompt match or Exit Code Probe token arrived. A nonzero `exit_code` is still `completed`.
  - `quiet` and `timeout` only end observation. They never prove the command finished and never justify an automatic resend. `completed` does not prove asynchronous business work (such as an upgrade) finished.
- Port State values, exactly: `closed`, `open`, `lost`. Shell values, exactly: `ready`, `unknown` (never `not_ready` in this version).
- Shell Readiness freshness: new send, reconnect, mode change, lost port, or Target Prompt change clears readiness. With no new evidence the value is `unknown`. The Hub never sends a probe.
- `raw=true` returns `raw_base64` of the first 32 KiB (counted before encoding) of the unmodified capture window and `raw_truncated`; independent of Grep and `max_lines`.
- Start-of-bridge failures never auto-revert to CRT Mode. Even when every port fails, report `mode: "bridge"`, every Target `open: false`, and each error.
- Code, comments and commit messages are English.

## File Structure

- Modify `serial_bridge/hub/queue.py`: `exec_result(status=...)`, `ExecSpec.raw`, `ExecRequest.raw`, `TargetQueue.abort_agents(disconnected=...)`.
- Modify `serial_bridge/hub/exec.py`: status mapping in `_finish`, Raw Capture, `SerialException` handling.
- Modify `serial_bridge/hub/worker.py`: `lost`, readiness observation/clearing, `hub.port_lost`.
- Create `serial_bridge/hub/readiness.py`: `ShellReadiness` (one responsibility: freshness-bound prompt observation).
- Modify `serial_bridge/hub/mode_transition.py`: no rollback, per-Target results.
- Modify `serial_bridge/hub/core.py`: `open_errors`, `port_lost`, `set_mode_agent`, permission, target prompts, extended `status()`.
- Modify `serial_bridge/config.py`: `Config.target_prompts`, load/persist.
- Modify `serial_bridge/operator.py`: `POST /api/mode_switch_permission`, `POST /api/target_prompt` (both `_require_operator_access`).
- Modify `serial_bridge/mcp_server.py`: `serial_set_mode`, `serial_exec(raw=...)`, docstrings.
- Modify `static/index.html`, `static/app.js`: permission toggle, Target Prompt input, per-Target open failures.
- Modify tests: `tests/test_exec.py`, `tests/test_hub.py`, `tests/test_config.py`, `tests/test_mcp.py`, `tests/test_app.py`, `tests/conftest.py`, `tests/test_ground_station_exec_ui.py`; create `tests/test_readiness.py`.
- Modify `CONTEXT.md` (Target Prompt wording), `README.md` (MCP tool list).

Before starting, run `git status` and leave the unrelated untracked files (`docs/adr/0026-*`, `docs/superpowers/plans/2026-08-31-*`, `docs/superpowers/specs/2026-09-18-*`) untouched. Do not stage them.

---

### Task 1: Exec Status

**Files:**
- Modify: `serial_bridge/hub/queue.py` (`exec_result`, lines ~67-101)
- Modify: `serial_bridge/hub/exec.py` (`_finish`, lines ~269-277)
- Test: `tests/test_exec.py`

**Interfaces:**
- Produces: every Exec envelope has `status` in `{completed, quiet, timeout, disconnected, aborted, error}`. `exec_result(target, *, ok, ..., status: str | None = None, ...)`. Derivation when `status` is None: `aborted` -> `"aborted"`, `timed_out` -> `"timeout"`, `error is not None` -> `"error"`, `ok` -> `"quiet"` (weakest claim), else `"error"`.
- `ExecEngine._finish(on_done, ended_by, result)` now sets `result["status"]` from `ended_by` (`prompt`->completed, `idle`->quiet, `timeout`->timeout, `abort`->aborted, `error`->error, `disconnect`->disconnected).

- [ ] **Step 1: Write the failing tests** (add inside the existing exec test class in `tests/test_exec.py`; reuse the module's `execute` helper and `TOKEN`)

```python
    def test_status_completed_on_prompt_match(self):
        result, _, _ = execute([(0.0, b"show\r\nok\r\nrouter# ")], prompt="router#")
        self.assertEqual("completed", result["status"])

    def test_nonzero_exit_code_is_still_completed(self):
        out = f"x\r\n3\r\n{TOKEN}\r\n".encode()
        result, _, _ = execute([(0.0, out)], exit_code=True)
        self.assertEqual("completed", result["status"])
        self.assertEqual(3, result["exit_code"])

    def test_status_quiet_when_output_goes_idle(self):
        result, _, _ = execute([(0.0, b"show\r\npartial")])
        self.assertTrue(result["ok"])
        self.assertEqual("quiet", result["status"])

    def test_status_timeout_when_window_expires(self):
        def chatter():
            return b"x"

        result, _, _ = execute(serial_factory=lambda clock: ScriptedSerial(clock, on_read=chatter))
        self.assertEqual("timeout", result["status"])
        self.assertFalse(result["ok"])

    def test_status_aborted(self):
        result, _, _ = execute(abort_before_execute=True)
        self.assertEqual("aborted", result["status"])

    def test_status_error_on_invalid_option(self):
        result, _, _ = execute(grep="")
        self.assertEqual("error", result["status"])
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_exec.py -q -k "status"`
Expected: FAIL with `KeyError: 'status'`.

- [ ] **Step 3: Implement**

In `serial_bridge/hub/queue.py` change the signature and body of `exec_result`:

```python
def exec_result(
    target: str,
    *,
    ok: bool,
    output: str = "",
    truncated: bool = False,
    timed_out: bool = False,
    aborted: bool = False,
    error: str | None = None,
    grepped: bool | None = None,
    match_count: int | None = None,
    status: str | None = None,
    **extras: Any,
) -> dict[str, Any]:
    """... (keep the existing docstring) ``status`` is the Exec Status; when
    omitted it is derived from the flags, and a bare ok result is ``quiet``
    because that claims the least."""
    if status is None:
        if aborted:
            status = "aborted"
        elif timed_out:
            status = "timeout"
        elif error is not None:
            status = "error"
        else:
            status = "quiet" if ok else "error"
    result: dict[str, Any] = {"ok": ok, "status": status, "output": output}
```

(leave the rest of the function unchanged.)

In `serial_bridge/hub/exec.py` add above `class ExecEngine`:

```python
_STATUS_BY_ENDED_BY = {
    "prompt": "completed",
    "idle": "quiet",
    "timeout": "timeout",
    "abort": "aborted",
    "error": "error",
    "disconnect": "disconnected",
}
```

and replace `_finish`:

```python
    @staticmethod
    def _finish(
        on_done: Callable[[str], None] | None,
        ended_by: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        result["status"] = _STATUS_BY_ENDED_BY[ended_by]
        if on_done is not None:
            on_done(ended_by)
        return result
```

- [ ] **Step 4: Run the full suite and fix expectations**

Run: `python -m pytest tests -q -x`
Expected: the new tests PASS. Existing tests that compare whole Exec dicts fail only because of the new `status` key; update each expected dict to include the correct `status` (prompt -> `completed`, idle -> `quiet`, timeout -> `timeout`, abort -> `aborted`, any `error` -> `error`). Do not change any other assertion.

- [ ] **Step 5: Commit**

```bash
git add serial_bridge/hub/queue.py serial_bridge/hub/exec.py tests
git commit -m "feat: report Exec Status on every Exec result"
```

---

### Task 2: Raw Capture

**Files:**
- Modify: `serial_bridge/hub/queue.py` (`ExecSpec`, `ExecRequest`, `TargetQueue.enqueue_exec`)
- Modify: `serial_bridge/hub/exec.py` (`_result_from_capture`)
- Test: `tests/test_exec.py`

**Interfaces:**
- Produces: `ExecSpec.raw: bool = False`; with `raw=True` the result has `raw_base64: str` and `raw_truncated: bool`.

- [ ] **Step 1: Write the failing tests**

```python
    def test_raw_capture_keeps_echo_ansi_and_wrapper_bytes(self):
        import base64

        out = b"\x1b[1mshow\x1b[0m\r\nok\r\nrouter# "
        result, _, _ = execute([(0.0, out)], prompt="router#", raw=True)
        self.assertEqual(out, base64.b64decode(result["raw_base64"]))
        self.assertFalse(result["raw_truncated"])
        self.assertNotIn("\x1b", result["output"])

    def test_raw_capture_ignores_grep_and_max_lines(self):
        import base64

        out = b"show\r\na\r\nb\r\nc\r\n"
        result, _, _ = execute([(0.0, out)], grep="b", max_lines=1, raw=True)
        self.assertEqual(out, base64.b64decode(result["raw_base64"]))

    def test_raw_capture_truncates_to_first_32_kib_before_encoding(self):
        import base64

        out = b"A" * (32 * 1024 + 10)
        result, _, _ = execute([(0.0, out)], raw=True)
        raw = base64.b64decode(result["raw_base64"])
        self.assertEqual(32 * 1024, len(raw))
        self.assertTrue(result["raw_truncated"])

    def test_raw_fields_absent_by_default(self):
        result, _, _ = execute([(0.0, b"show\r\nok\r\n")])
        self.assertNotIn("raw_base64", result)
```

Also extend the test module's `execute` helper: add a `raw=False` parameter and pass `raw=raw` to `queue.enqueue_exec(...)`.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_exec.py -q -k "raw"`
Expected: FAIL with `TypeError: ... unexpected keyword argument 'raw'`.

- [ ] **Step 3: Implement**

`serial_bridge/hub/queue.py`: add `raw: bool = False` as the last field of `ExecSpec` (after `exit_code`) and of `ExecRequest` (after `exit_code`, before `done`); add `raw: bool = False` to `TargetQueue.enqueue_exec` parameters and pass `raw=raw` into `ExecRequest(...)`. `as_exec_options` picks it up automatically.

`serial_bridge/hub/exec.py`, in `_result_from_capture` just before `return exec_result(...)`:

```python
        if request.raw:
            raw = bytes(captured[: self.OUTPUT_CAP_BYTES])
            extras["raw_base64"] = base64.b64encode(raw).decode("ascii")
            extras["raw_truncated"] = len(captured) > self.OUTPUT_CAP_BYTES
```

and add `import base64` at the top of the file.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_exec.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add serial_bridge/hub tests/test_exec.py
git commit -m "feat: optional Raw Capture on Exec"
```

---

### Task 3: Disconnect handling

**Files:**
- Modify: `serial_bridge/hub/exec.py` (`execute`)
- Modify: `serial_bridge/hub/queue.py` (`abort_agents`, `finish_queued_abort`)
- Modify: `serial_bridge/hub/worker.py` (`__init__`, `_run`)
- Modify: `serial_bridge/hub/core.py` (new `port_lost`)
- Test: `tests/test_exec.py`, `tests/test_hub.py`

**Interfaces:**
- Produces: `PortWorker.lost: bool`; `Hub.port_lost(target: str) -> None` (emits a status broadcast and rewrites `bridge_status.json`); `TargetQueue.abort_agents(disconnected: bool = False)`; Exec result `status="disconnected"`, `ok=False`, `error=<exception text>`, with partial `output` kept.
- A completed Exec is never rewritten by a later disconnect.

- [ ] **Step 1: Write the failing tests**

In `tests/test_exec.py`:

```python
    def test_serial_exception_mid_exec_is_disconnected_with_partial_output(self):
        from serial import SerialException

        state = {"n": 0}

        def read_then_fail():
            state["n"] += 1
            if state["n"] == 1:
                return b"show\r\npartial line\r\n"
            raise SerialException("device removed")

        result, _, _ = execute(
            serial_factory=lambda clock: ScriptedSerial(clock, on_read=read_then_fail)
        )
        self.assertFalse(result["ok"])
        self.assertEqual("disconnected", result["status"])
        self.assertIn("partial line", result["output"])
        self.assertIn("device removed", result["error"])

    def test_queued_exec_finishes_disconnected(self):
        queue = TargetQueue()
        queued = queue.enqueue_exec(target="linux", cmd="a")
        queue.abort_agents(disconnected=True)
        self.assertEqual("disconnected", queued.result["status"])
```

(`TargetQueue` and the `execute` helper are already imported/defined in that module.)

In `tests/test_hub.py` add to `FakePortWorker.__init__`: `self.lost = False`. Then add to `HubTest`:

```python
    def test_port_lost_broadcasts_status_and_keeps_bridge_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            live = Path(temp_dir)
            with patch.object(hub_module, "PortWorker", FakePortWorker):
                hub = Hub(make_config(live / "serial_bridge.json", live_dir=live))
                hub.start_bridge()
                events = []
                hub.emit = events.append
                hub.workers["linux"].is_open = False
                hub.workers["linux"].lost = True
                hub.port_lost("linux")
            self.assertEqual("bridge", hub.mode)
            self.assertEqual("status", events[-1]["type"])
```

(`port_state` is asserted in Task 4, where `lost` becomes visible in status.)

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_exec.py tests/test_hub.py -q -k "disconnect or port_lost"`
Expected: FAIL (`SerialException` propagates; `abort_agents()` got unexpected keyword; `Hub` has no `port_lost`).

- [ ] **Step 3: Implement**

`queue.py`:

```python
    def finish_queued_abort(self, disconnected: bool = False) -> None:
        if disconnected:
            self.result = exec_result(
                self.target, ok=False, status="disconnected", error="port lost"
            )
        else:
            self.result = exec_result(self.target, ok=False, aborted=True)
        self.done.set()
```

and in `TargetQueue.abort_agents(self, disconnected: bool = False)` call `request.finish_queued_abort(disconnected)` for queued `ExecRequest`s (the active request handling is unchanged).

`exec.py`: add `from serial import SerialException` and wrap the body of `execute` from the `wrote = queue.write_if_allowed(...)` line through the end of the `while True` loop in:

```python
        try:
            ...existing write / flush / loop...
        except SerialException as exc:
            return self._finish(
                on_done, "disconnect", present(ok=False, error=str(exc))
            )
```

(Indent the existing code; do not change its logic.)

`worker.py`: in `__init__` add `self.lost = False`; in `_run`, inside the `if isinstance(request, ExecRequest):` branch, immediately after the `request.result = ExecSession(...).execute(...)` assignment (still inside the inner `try`), add:

```python
                            if request.result.get("status") == "disconnected":
                                raise SerialException(
                                    request.result.get("error") or "port lost"
                                )
```

and replace the `except SerialException as e:` block with:

```python
            except SerialException as e:
                self.hub.append_log(self.name, "---", f"SerialException: {e}", who="system")
                self.is_open = False
                self.lost = True
                self._tx.abort_agents(disconnected=True)
                self.hub.port_lost(self.name)
                break
```

`core.py`, next to `send`:

```python
    def port_lost(self, target: str) -> None:
        """A worker's port dropped: tell clients; Bridge Mode and ports stay as they are."""
        self.emit({"type": "status", **self.status()})
        self._mode_transition.write_bridge_status()
```

In `tests/test_hub.py` the `WorkerHub` double also needs `def port_lost(self, target): pass`.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add serial_bridge tests
git commit -m "feat: report disconnected Exec and broadcast lost ports"
```

---

### Task 4: Port State and per-Target open results (no rollback)

**Files:**
- Modify: `serial_bridge/hub/mode_transition.py` (`start_bridge`)
- Modify: `serial_bridge/hub/core.py` (`__init__`, `status`)
- Test: `tests/test_hub.py`

**Interfaces:**
- Produces: `Hub.open_errors: dict[str, str]` (Target -> last open error, cleared by each `start_bridge`/`stop_bridge`). `status()["ports"][k]` gains `port_state` (`closed|open|lost`) and, when present, `open_error`.
- `start_bridge()` returns on port failures: `{"ok": True, "mode": "bridge", "all_open": False, "ports": {key: {"open": bool, "error"?: str}}}`. On full success the same shape with `all_open: True`. Live Directory creation failure keeps the existing `{"ok": False, "mode": "crt", "error": ...}`.
- `stop_bridge()` result and mode semantics unchanged.

- [ ] **Step 1: Write the failing tests** (class `HubTest`; extend `FakePortWorker` first)

Add to `FakePortWorker`:

```python
    fail_ports: set[str] = set()

    def open(self):
        if self.port in self.fail_ports:
            raise SerialException(f"{self.port} busy")
        self.is_open = True
```

(import `from serial import SerialException` at the top of `tests/test_hub.py` if missing; reset `FakePortWorker.fail_ports = set()` wherever `instances` is reset, and in each test below via `addCleanup`.)

```python
    def _bridge_hub(self, temp_dir):
        live = Path(temp_dir)
        return Hub(make_config(live / "serial_bridge.json", live_dir=live))

    def test_partial_open_failure_stays_in_bridge_and_reports_each_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            FakePortWorker.fail_ports = {"COM6"}
            self.addCleanup(setattr, FakePortWorker, "fail_ports", set())
            with patch.object(hub_module, "PortWorker", FakePortWorker):
                hub = self._bridge_hub(temp_dir)
                result = hub.start_bridge()
                status = hub.status()
            self.assertTrue(result["ok"])
            self.assertEqual("bridge", result["mode"])
            self.assertFalse(result["all_open"])
            self.assertTrue(result["ports"]["linux"]["open"])
            self.assertFalse(result["ports"]["rtos"]["open"])
            self.assertIn("COM6", result["ports"]["rtos"]["error"])
            self.assertEqual("bridge", hub.mode)
            self.assertEqual("open", status["ports"]["linux"]["port_state"])
            self.assertEqual("closed", status["ports"]["rtos"]["port_state"])
            self.assertIn("COM6", status["ports"]["rtos"]["open_error"])

    def test_all_ports_failing_still_reports_bridge_mode_with_all_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            FakePortWorker.fail_ports = {"COM3", "COM6"}
            self.addCleanup(setattr, FakePortWorker, "fail_ports", set())
            with patch.object(hub_module, "PortWorker", FakePortWorker):
                hub = self._bridge_hub(temp_dir)
                result = hub.start_bridge()
            self.assertEqual("bridge", result["mode"])
            self.assertFalse(any(p["open"] for p in result["ports"].values()))
            self.assertEqual("bridge", hub.mode)

    def test_lost_port_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(hub_module, "PortWorker", FakePortWorker):
                hub = self._bridge_hub(temp_dir)
                hub.start_bridge()
                hub.workers["linux"].is_open = False
                hub.workers["linux"].lost = True
                self.assertEqual("lost", hub.status()["ports"]["linux"]["port_state"])
                hub.stop_bridge()
                self.assertEqual("closed", hub.status()["ports"]["linux"]["port_state"])
```

Check the default Target slots use `COM3`/`COM6` (`DEFAULT_SLOTS`); if `make_config` binds other COM names, use those in `fail_ports`.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_hub.py -q -k "open_failure or all_ports_failing or lost_port_state"`
Expected: FAIL (`mode` is `crt`, no `ports`/`port_state` keys).

- [ ] **Step 3: Implement**

`core.py` `__init__`: after `self.workers = {}` add `self.open_errors: dict[str, str] = {}`. In `status()`, capture `open_errors = dict(self.open_errors)` under the lock and build each port entry with:

```python
                    "port_state": self._port_state(k, workers),
```

plus, after the dict is built, `if k in open_errors: entry["open_error"] = open_errors[k]` (restructure the comprehension into a small loop if needed). Add:

```python
    @staticmethod
    def _port_state(key: str, workers: dict[str, Any]) -> str:
        worker = workers.get(key)
        if worker is None:
            return "closed"
        if getattr(worker, "lost", False):
            return "lost"
        return "open" if worker.is_open else "closed"
```

`mode_transition.py` `start_bridge`: after `self.stop_bridge(quiet=True)` add `self._hub.open_errors.clear()` (under `_state_lock`). Replace the per-worker loop and the `if errors:` rollback block with:

```python
            results: dict[str, dict[str, Any]] = {}
            for key, config in self._hub.ports.items():
                worker = self._worker_factory(key, config["com"], config["baud"])
                try:
                    worker.open()
                    worker.start()
                    with self._hub._state_lock:
                        self._hub.workers[key] = worker
                    results[key] = {"open": True}
                except SerialException as exc:
                    message = f"{config['com']}: {exc}"
                    worker.close()
                    with self._hub._state_lock:
                        self._hub.open_errors[key] = message
                    results[key] = {"open": False, "error": message}
```

then keep the existing "mode = bridge" / status / system-message / `write_bridge_status` tail, changing the system text when something failed and the return value:

```python
            failed = [k for k, r in results.items() if not r["open"]]
            ...
            if failed:
                self._hub.emit(
                    {
                        "type": "system",
                        "text": "Bridge Mode: not open - "
                        + "; ".join(f"{k}: {results[k]['error']}" for k in failed),
                    }
                )
            ...
            return {
                "ok": True,
                "mode": "bridge",
                "all_open": not failed,
                "ports": results,
            }
```

Update the early "Already in Bridge Mode" return to also include `"all_open": True` and `"ports": {k: {"open": True} for k in self._hub.ports}`. In `stop_bridge`, also `self._hub.open_errors.clear()`.

- [ ] **Step 4: Run the suite and update superseded tests**

Run: `python -m pytest tests -q`
Expected: new tests PASS. Existing tests that asserted rollback on open failure (`ok False`, `mode crt`, `"Failed to open serial ports"`) are now obsolete by design; rewrite them to the new contract (partial/all failure stays `bridge`). Keep `test_mkdir_failure_keeps_crt_mode` unchanged.

- [ ] **Step 5: Commit**

```bash
git add serial_bridge tests
git commit -m "feat: report per-Target open results and Port State without rollback"
```

---

### Task 5: Target Prompt configuration

**Files:**
- Modify: `serial_bridge/config.py` (`Config`, `load_config`, `persist_slots`)
- Modify: `serial_bridge/hub/core.py` (new `set_target_prompt`)
- Modify: `serial_bridge/operator.py` (new route)
- Test: `tests/test_config.py`, `tests/test_hub.py`, `tests/test_app.py`

**Interfaces:**
- Produces: `Config.target_prompts: dict[str, str]` (Target Name -> regular expression). `persist_slots` keeps writing it. `Hub.set_target_prompt(target: object, pattern: object) -> dict` returns `{"ok": True, **status}` or `{"ok": False, "error": str}`; empty string means "not configured". `POST /api/target_prompt` body `{target: str, pattern: str}` (Operator access, loopback-only). `status()["ports"][k]["target_prompt"]` is the pattern or `""`.
- Consumes: `Hub.clear_readiness(target)` from Task 6 is called here; until Task 6 exists, implement it as a no-op in this task and replace the body in Task 6.

- [ ] **Step 1: Write the failing tests**

`tests/test_config.py` (use the file's existing temp-dir helpers; shown self-contained):

```python
class TargetPromptConfigTest(unittest.TestCase):
    def test_target_prompts_round_trip_and_survive_slot_saves(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "serial_bridge.json"
            config = load_config(environ={}, config_path=path)
            config.target_prompts = {"linux": r"\$ $"}
            persist_slots(config, config.slots)
            loaded = load_config(environ={}, config_path=path)
            self.assertEqual({"linux": r"\$ $"}, loaded.target_prompts)

    def test_invalid_saved_prompt_is_dropped_with_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "serial_bridge.json"
            config = load_config(environ={}, config_path=path)
            persist_slots(config, config.slots)
            data = json.loads(path.read_text(encoding="utf-8"))
            data["target_prompts"] = {"linux": "("}
            path.write_text(json.dumps(data), encoding="utf-8")
            loaded = load_config(environ={}, config_path=path)
            self.assertEqual({}, loaded.target_prompts)
            self.assertIn("target_prompts", loaded.warning)
```

`tests/test_hub.py` (`HubTest`):

```python
    def test_set_target_prompt_validates_persists_and_reports(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            live = Path(temp_dir)
            hub = Hub(make_config(live / "serial_bridge.json", live_dir=live))
            bad = hub.set_target_prompt("linux", "(")
            self.assertFalse(bad["ok"])
            self.assertEqual("", hub.status()["ports"]["linux"]["target_prompt"])
            good = hub.set_target_prompt("linux", r"# $")
            self.assertTrue(good["ok"])
            self.assertEqual(r"# $", hub.status()["ports"]["linux"]["target_prompt"])
            self.assertIn(
                "target_prompts",
                json.loads((live / "serial_bridge.json").read_text(encoding="utf-8")),
            )
            self.assertFalse(hub.set_target_prompt("nope", "x")["ok"])
            self.assertTrue(hub.set_target_prompt("linux", "")["ok"])
            self.assertEqual("", hub.status()["ports"]["linux"]["target_prompt"])
```

`tests/test_app.py`: follow its existing `/api/bindings` test pattern (loopback client posts, non-loopback is refused) and add:

```python
    def test_target_prompt_endpoint_is_operator_only(self):
        # same client fixtures as the /api/bindings test in this file
        ok = self.local_client.post("/api/target_prompt", json={"target": "linux", "pattern": "# $"})
        self.assertEqual(200, ok.status_code)
        denied = self.remote_client.post("/api/target_prompt", json={"target": "linux", "pattern": "# $"})
        self.assertEqual(403, denied.status_code)
```

(Rename `local_client` / `remote_client` to whatever the neighbouring bindings test uses; the FakeHub in `tests/conftest.py` needs `def set_target_prompt(self, target, pattern): self.calls.append(("target_prompt", target, pattern)); return {"ok": True}`.)

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_config.py tests/test_hub.py tests/test_app.py -q -k "prompt"`
Expected: FAIL (`Config` has no `target_prompts`, etc.).

- [ ] **Step 3: Implement**

`config.py`: change the import to `from dataclasses import dataclass, field`; add to `Config`: `target_prompts: dict[str, str] = field(default_factory=dict)`. Add helpers:

```python
def _parse_saved_target_prompts(data: object) -> dict[str, str]:
    raw = data.get("target_prompts") if isinstance(data, dict) else None
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("target_prompts must be an object")
    prompts: dict[str, str] = {}
    for name, pattern in raw.items():
        if not isinstance(name, str) or not isinstance(pattern, str):
            raise ValueError("target_prompts entries must be strings")
        re.compile(pattern)  # re.error is a ValueError subclass? no: wrap below
        prompts[name] = pattern
    return prompts
```

`re.error` is not a `ValueError`; wrap: `try: re.compile(pattern) except re.error as exc: raise ValueError(f"target_prompts[{name}] is not a valid regex: {exc}") from exc`.

In `load_config`, inside the `try` after `saved = _parse_saved_slots(raw)`, **after** `slots = candidate`, add:

```python
            try:
                target_prompts = _parse_saved_target_prompts(raw)
            except ValueError as exc:
                warning = f"Could not load config {path}: target_prompts: {exc}"
```

with `target_prompts: dict[str, str] = {}` initialised before the `if path.is_file():` block, and pass `target_prompts=target_prompts` into the final `Config(...)`.

`persist_slots`: write `"target_prompts": {k: v for k, v in config.target_prompts.items() if k in {s["name"] for s in validated}}` into the JSON object next to `slots`.

`core.py`:

```python
    def clear_readiness(self, target: str) -> None:  # replaced in Task 6
        return None

    def set_target_prompt(self, target: object, pattern: object) -> dict[str, Any]:
        target_name, error = self.resolve_target(target)
        if error is not None:
            return {"ok": False, "error": error}
        if not isinstance(pattern, str):
            return {"ok": False, "error": "pattern must be a string"}
        if pattern:
            try:
                re.compile(pattern)
            except re.error as exc:
                return {"ok": False, "error": f"pattern is not a valid regex: {exc}"}
        with self._transition_lock:
            with self._state_lock:
                updated = dict(self.config.target_prompts)
                if pattern:
                    updated[target_name] = pattern
                else:
                    updated.pop(target_name, None)
                previous = self.config.target_prompts
                self.config.target_prompts = updated
                try:
                    persist_slots(self.config, self.config.slots)
                except (OSError, UnicodeError, ValueError) as exc:
                    self.config.target_prompts = previous
                    return {"ok": False, "error": f"Could not save Target Prompt: {exc}"}
            self.clear_readiness(target_name)
        status = self.status()
        self.emit({"type": "status", **status})
        return {"ok": True, **status}
```

(add `import re` to `core.py`.) In `status()` add `"target_prompt": self.config.target_prompts.get(k, "")` to each port entry.

`operator.py`:

```python
class TargetPromptBody(BaseModel):
    target: str = Field(min_length=1)
    pattern: str = ""
```

and inside `register_operator_routes`:

```python
    @app.post("/api/target_prompt", dependencies=[Depends(_require_operator_access)])
    async def api_target_prompt(body: TargetPromptBody) -> dict[str, Any]:
        return await offload(_get_hub().set_target_prompt, body.target, body.pattern)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add serial_bridge tests
git commit -m "feat: Operator-configured Target Prompt"
```

---

### Task 6: Shell Readiness with freshness rules

**Files:**
- Create: `serial_bridge/hub/readiness.py`
- Modify: `serial_bridge/hub/worker.py` (`_log_rx_chunk`, `_write_request`, Exec `on_tx`)
- Modify: `serial_bridge/hub/core.py` (readiness wiring, `status()`)
- Modify: `serial_bridge/hub/mode_transition.py` (clear on start/stop)
- Test: `tests/test_readiness.py` (create), `tests/test_hub.py`

**Interfaces:**
- Produces `ShellReadiness`:
  - `observe(target: str, text: str, at: str) -> None` appends ANSI-stripped RX text (keeps the last 512 chars) and records `at`.
  - `clear(target: str | None = None) -> None` drops one Target or all.
  - `evaluate(target: str, pattern: str | None) -> tuple[str, str | None]` returns `("ready", observed_at)` only when `pattern` is set, there is an observation, the text after the last newline (CR stripped) is non-blank, and `re.search(pattern, that_line)` matches; otherwise `("unknown", None)`.
- Hub: `observe_rx(target, chunk: bytes)`, `clear_readiness(target)` (replaces the Task 5 stub), `clear_all_readiness()`. `status()` ports gain `shell` and `shell_observed_at`.
- Clearing triggers: any TX to the Target (Operator, Agent, Exec), `port_lost`, `start_bridge`, `stop_bridge`, `set_target_prompt`.

- [ ] **Step 1: Write the failing tests**

`tests/test_readiness.py`:

```python
import unittest

from serial_bridge.hub.readiness import ShellReadiness


class ShellReadinessTest(unittest.TestCase):
    def test_unknown_without_prompt_or_observation(self):
        tracker = ShellReadiness()
        self.assertEqual(("unknown", None), tracker.evaluate("linux", r"# $"))
        tracker.observe("linux", "root@dev:~# ", "t1")
        self.assertEqual(("unknown", None), tracker.evaluate("linux", None))

    def test_ready_when_last_line_matches_prompt(self):
        tracker = ShellReadiness()
        tracker.observe("linux", "output\r\nroot@dev:~# ", "t1")
        self.assertEqual(("ready", "t1"), tracker.evaluate("linux", r"# $"))

    def test_trailing_newline_after_prompt_is_not_ready(self):
        tracker = ShellReadiness()
        tracker.observe("linux", "root@dev:~# \r\n", "t1")
        self.assertEqual(("unknown", None), tracker.evaluate("linux", r"# $"))

    def test_later_output_replaces_the_evidence(self):
        tracker = ShellReadiness()
        tracker.observe("linux", "root@dev:~# ", "t1")
        tracker.observe("linux", "kernel: oops", "t2")
        self.assertEqual(("unknown", None), tracker.evaluate("linux", r"# $"))

    def test_clear_drops_old_readiness(self):
        tracker = ShellReadiness()
        tracker.observe("linux", "root@dev:~# ", "t1")
        tracker.clear("linux")
        self.assertEqual(("unknown", None), tracker.evaluate("linux", r"# $"))

    def test_ansi_is_stripped_before_matching(self):
        tracker = ShellReadiness()
        tracker.observe("linux", "\x1b[32mroot\x1b[0m# ", "t1")
        self.assertEqual(("ready", "t1"), tracker.evaluate("linux", r"root# $"))

    def test_targets_are_independent(self):
        tracker = ShellReadiness()
        tracker.observe("linux", "# ", "t1")
        tracker.clear("rtos")
        self.assertEqual("ready", tracker.evaluate("linux", r"# $")[0])
```

`tests/test_hub.py` (`HubTest`, uses `FakePortWorker`; no real serial):

```python
    def test_status_shell_ready_then_cleared_by_each_freshness_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            live = Path(temp_dir)
            with patch.object(hub_module, "PortWorker", FakePortWorker):
                hub = Hub(make_config(live / "serial_bridge.json", live_dir=live))
                hub.set_target_prompt("linux", r"# $")
                hub.start_bridge()
                self.assertEqual("unknown", hub.status()["ports"]["linux"]["shell"])
                hub.observe_rx("linux", b"root@dev:~# ")
                port = hub.status()["ports"]["linux"]
                self.assertEqual("ready", port["shell"])
                self.assertIsNotNone(port["shell_observed_at"])

                hub.clear_readiness("linux")  # a send
                self.assertEqual("unknown", hub.status()["ports"]["linux"]["shell"])

                hub.observe_rx("linux", b"# ")
                hub.port_lost("linux")
                self.assertEqual("unknown", hub.status()["ports"]["linux"]["shell"])

                hub.observe_rx("linux", b"# ")
                hub.stop_bridge()
                self.assertEqual("unknown", hub.status()["ports"]["linux"]["shell"])

                hub.start_bridge()
                self.assertEqual("unknown", hub.status()["ports"]["linux"]["shell"])

                hub.observe_rx("linux", b"# ")
                hub.set_target_prompt("linux", r"\$ $")
                self.assertEqual("unknown", hub.status()["ports"]["linux"]["shell"])

    def test_hub_send_clears_readiness(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            live = Path(temp_dir)
            with patch.object(hub_module, "PortWorker", FakePortWorker):
                hub = Hub(make_config(live / "serial_bridge.json", live_dir=live))
                hub.set_target_prompt("linux", r"# $")
                hub.start_bridge()
                hub.observe_rx("linux", b"# ")
                hub.send("linux", "ls", who="user")
                self.assertEqual("unknown", hub.status()["ports"]["linux"]["shell"])
```

Add `def observe_rx(self, target, chunk): pass` and `def clear_readiness(self, target): pass` to the `WorkerHub` test double.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_readiness.py tests/test_hub.py -q -k "readiness or shell"`
Expected: FAIL (`ModuleNotFoundError: serial_bridge.hub.readiness`).

- [ ] **Step 3: Implement**

`serial_bridge/hub/readiness.py`:

```python
"""Freshness-bound Shell Readiness: ready only while the newest RX ends at the prompt."""
from __future__ import annotations

import re
import threading

from serial_bridge.hub.text import strip_ansi

_KEEP_CHARS = 512


class ShellReadiness:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tail: dict[str, str] = {}
        self._observed_at: dict[str, str] = {}

    def observe(self, target: str, text: str, at: str) -> None:
        clean = strip_ansi(text)
        with self._lock:
            self._tail[target] = (self._tail.get(target, "") + clean)[-_KEEP_CHARS:]
            self._observed_at[target] = at

    def clear(self, target: str | None = None) -> None:
        with self._lock:
            if target is None:
                self._tail.clear()
                self._observed_at.clear()
            else:
                self._tail.pop(target, None)
                self._observed_at.pop(target, None)

    def evaluate(self, target: str, pattern: str | None) -> tuple[str, str | None]:
        if not pattern:
            return "unknown", None
        with self._lock:
            tail = self._tail.get(target)
            at = self._observed_at.get(target)
        if not tail or at is None:
            return "unknown", None
        last_line = tail.rsplit("\n", 1)[-1].replace("\r", "")
        if not last_line.strip():
            return "unknown", None
        try:
            matched = re.search(pattern, last_line) is not None
        except re.error:
            return "unknown", None
        return ("ready", at) if matched else ("unknown", None)
```

(Confirm `strip_ansi` signature in `serial_bridge/hub/text.py` accepts `str`; `exec.py` already calls it, so reuse the same call form.)

`core.py`: import `ShellReadiness`; in `__init__` add `self._readiness = ShellReadiness()` (before `ModeTransition`); replace the Task 5 stub:

```python
    def observe_rx(self, target: str, chunk: bytes) -> None:
        self._readiness.observe(
            target,
            chunk.decode("utf-8", errors="replace"),
            datetime.now().astimezone().isoformat(timespec="milliseconds"),
        )

    def clear_readiness(self, target: str) -> None:
        self._readiness.clear(target)

    def clear_all_readiness(self) -> None:
        self._readiness.clear()
```

(Use `import serial_bridge.hub as hub` indirection like `__init__` does only if tests patch `hub.datetime`; a plain `from datetime import datetime` at module top is fine here and does not disturb the existing patches, which target the package-level name.) In `status()` per port: 

```python
shell, observed_at = self._readiness.evaluate(k, self.config.target_prompts.get(k))
entry["shell"] = shell
entry["shell_observed_at"] = observed_at
```

In `port_lost` first line add `self._readiness.clear(target)`. In `_send` and `exec`, immediately before `worker.send(...)` / `worker.enqueue_exec(...)` add `self._readiness.clear(target)`.

`mode_transition.py`: call `self._hub.clear_all_readiness()` at the start of `start_bridge` (after the already-bridge early return) and in `stop_bridge` after the workers are cleared.

`worker.py`: at the end of `_log_rx_chunk(self, chunk)` add `self.hub.observe_rx(self.name, chunk)` (if the method has early returns, call it at the top instead); in `_write_request` and in the Exec `on_tx` lambda add `self.hub.clear_readiness(self.name)` (the lambda becomes a small nested function that logs, then clears).

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add serial_bridge tests
git commit -m "feat: freshness-bound Shell Readiness"
```

---

### Task 7: Mode Switch Permission and `Hub.set_mode_agent`

**Files:**
- Modify: `serial_bridge/hub/core.py`
- Modify: `serial_bridge/operator.py`
- Test: `tests/test_hub.py`, `tests/test_app.py`

**Interfaces:**
- Produces:
  - `Hub.set_mode_switch_permission(allowed: bool) -> dict` (returns `{"ok": True, **status}` and broadcasts status).
  - `Hub.set_mode_agent(mode: object) -> dict`. Results:
    - refused, not allowed: `{"ok": False, "error": "Mode switching by Agents is not permitted", "mode_switch": {...}}`
    - refused, busy: `{"ok": False, "error": "Exec in flight", "busy_targets": [...], "mode_switch": {...}}`
    - invalid mode: `{"ok": False, "error": "mode must be bridge or crt"}`
    - accepted: the `start_bridge()` / `stop_bridge()` result.
  - `status()["mode_switch"] = {"allowed": bool, "busy": bool, "busy_targets": [str], "next_action": str}` where `next_action` is `"ask_operator_to_enable_mode_switch"` (not allowed), `"wait_for_exec_to_finish"` (allowed and busy), or `"call serial_set_mode"` (allowed and free).
  - `POST /api/mode_switch_permission` body `{allowed: bool}`, Operator access.
- `Hub.exec` and `_send` refuse with `"mode switch in progress"` while a switch is starting (`self._switching`).

- [ ] **Step 1: Write the failing tests** (`HubTest`, using `FakePortWorker`)

```python
    def _perm_hub(self, temp_dir):
        live = Path(temp_dir)
        return Hub(make_config(live / "serial_bridge.json", live_dir=live))

    def test_permission_defaults_off_and_agent_switch_is_refused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(hub_module, "PortWorker", FakePortWorker):
                hub = self._perm_hub(temp_dir)
                status = hub.status()["mode_switch"]
                self.assertFalse(status["allowed"])
                self.assertEqual("ask_operator_to_enable_mode_switch", status["next_action"])
                result = hub.set_mode_agent("bridge")
            self.assertFalse(result["ok"])
            self.assertEqual("crt", hub.mode)

    def test_granted_permission_switches_both_directions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(hub_module, "PortWorker", FakePortWorker):
                hub = self._perm_hub(temp_dir)
                hub.set_mode_switch_permission(True)
                self.assertEqual("bridge", hub.set_mode_agent("bridge")["mode"])
                self.assertEqual("crt", hub.set_mode_agent("crt")["mode"])

    def test_busy_target_refuses_without_queueing_or_aborting(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(hub_module, "PortWorker", FakePortWorker):
                hub = self._perm_hub(temp_dir)
                hub.set_mode_switch_permission(True)
                hub.start_bridge()
                hub.workers["linux"].is_busy = True
                result = hub.set_mode_agent("crt")
                self.assertFalse(result["ok"])
                self.assertEqual(["linux"], result["busy_targets"])
                self.assertEqual("wait_for_exec_to_finish", result["mode_switch"]["next_action"])
                self.assertEqual("bridge", hub.mode)
                self.assertNotIn(("abort", "bridge"), hub.workers["linux"].events)

    def test_revoking_permission_affects_only_later_requests(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(hub_module, "PortWorker", FakePortWorker):
                hub = self._perm_hub(temp_dir)
                hub.set_mode_switch_permission(True)
                self.assertTrue(hub.set_mode_agent("bridge")["ok"])
                hub.set_mode_switch_permission(False)
                self.assertEqual("bridge", hub.mode)
                self.assertFalse(hub.set_mode_agent("crt")["ok"])

    def test_agent_switch_reports_partial_open_failure_without_revert(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            FakePortWorker.fail_ports = {"COM6"}
            self.addCleanup(setattr, FakePortWorker, "fail_ports", set())
            with patch.object(hub_module, "PortWorker", FakePortWorker):
                hub = self._perm_hub(temp_dir)
                hub.set_mode_switch_permission(True)
                result = hub.set_mode_agent("bridge")
            self.assertEqual("bridge", result["mode"])
            self.assertFalse(result["ports"]["rtos"]["open"])

    def test_exec_is_refused_while_switch_is_starting(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(hub_module, "PortWorker", FakePortWorker):
                hub = self._perm_hub(temp_dir)
                hub.start_bridge()
                hub._switching = True
                result = hub.exec(ExecSpec(target="linux", cmd="ls"))
            self.assertFalse(result["ok"])
            self.assertEqual("error", result["status"])
            self.assertIn("switch in progress", result["error"])

    def test_permission_is_memory_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            hub = self._perm_hub(temp_dir)
            hub.set_mode_switch_permission(True)
            self.assertFalse(Hub(hub.config).status()["mode_switch"]["allowed"])
```

(Import `ExecSpec` from `serial_bridge.hub.queue` in `tests/test_hub.py` if absent.)

`tests/test_app.py`: add the loopback-only test for `/api/mode_switch_permission` mirroring the `/api/target_prompt` test (FakeHub in `tests/conftest.py` gains `set_mode_switch_permission(self, allowed): self.calls.append(("permission", allowed)); return {"ok": True}`).

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests -q -k "permission or agent_switch or busy_target or switch_is_starting"`
Expected: FAIL (`Hub` has no `set_mode_switch_permission`).

- [ ] **Step 3: Implement** (`core.py`)

`__init__`: `self._mode_switch_allowed = False`, `self._switching = False`.

```python
    def _mode_switch_info(self, workers: dict[str, Any], allowed: bool) -> dict[str, Any]:
        busy_targets = sorted(k for k, w in workers.items() if w.is_busy)
        if not allowed:
            next_action = "ask_operator_to_enable_mode_switch"
        elif busy_targets:
            next_action = "wait_for_exec_to_finish"
        else:
            next_action = "call serial_set_mode"
        return {
            "allowed": allowed,
            "busy": bool(busy_targets),
            "busy_targets": busy_targets,
            "next_action": next_action,
        }

    def set_mode_switch_permission(self, allowed: bool) -> dict[str, Any]:
        with self._state_lock:
            self._mode_switch_allowed = bool(allowed)
        status = self.status()
        self.emit({"type": "status", **status})
        return {"ok": True, **status}

    def set_mode_agent(self, mode: object) -> dict[str, Any]:
        requested = mode.lower().strip() if isinstance(mode, str) else ""
        if requested not in ("bridge", "crt"):
            return {"ok": False, "error": "mode must be bridge or crt"}
        with self._transition_lock:
            with self._state_lock:
                info = self._mode_switch_info(dict(self.workers), self._mode_switch_allowed)
                if not info["allowed"]:
                    return {
                        "ok": False,
                        "error": "Mode switching by Agents is not permitted",
                        "mode_switch": info,
                    }
                if info["busy"]:
                    return {
                        "ok": False,
                        "error": "Exec in flight; mode not changed",
                        "busy_targets": info["busy_targets"],
                        "mode_switch": info,
                    }
                self._switching = True
            try:
                return self.start_bridge() if requested == "bridge" else self.stop_bridge()
            finally:
                with self._state_lock:
                    self._switching = False
```

In `status()` add `"mode_switch": self._mode_switch_info(workers, self._mode_switch_allowed)` (read `_mode_switch_allowed` inside the existing lock block). In `exec` and `_send`, inside the existing `with self._state_lock:` before the mode check:

```python
            if self._switching:
                return exec_result(target, ok=False, error="mode switch in progress; retry")
```

(for `_send` return `{"ok": False, "error": "mode switch in progress; retry"}`.)

`operator.py`:

```python
class PermissionBody(BaseModel):
    allowed: bool
```

```python
    @app.post(
        "/api/mode_switch_permission",
        dependencies=[Depends(_require_operator_access)],
    )
    async def api_mode_switch_permission(body: PermissionBody) -> dict[str, Any]:
        return await offload(_get_hub().set_mode_switch_permission, body.allowed)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add serial_bridge tests
git commit -m "feat: Operator-granted Mode Switch Permission for Agents"
```

---

### Task 8: MCP surface

**Files:**
- Modify: `serial_bridge/mcp_server.py`
- Modify: `tests/conftest.py` (`FakeHub`)
- Test: `tests/test_mcp.py`

**Interfaces:**
- Consumes: `Hub.set_mode_agent(mode)` (Task 7), `ExecSpec.raw` (Task 2).
- Produces: MCP tools `serial_status`, `serial_exec(..., raw: bool = False)`, `serial_send`, `serial_tail`, `serial_set_mode(mode: str)`. No tool lists ports or edits Port Binding.

- [ ] **Step 1: Write the failing tests**

`FakeHub` additions in `tests/conftest.py`:

```python
    def set_mode_agent(self, mode):
        self.calls.append(("agent_mode", mode))
        return {"ok": True, "mode": mode, "ports": {}}
```

In `tests/test_mcp.py` (reuse `call_tool` and the class's existing client setup; copy the arrangement of a neighbouring test such as the one that calls `serial_send`):

```python
    def test_set_mode_tool_is_listed_and_calls_hub(self):
        result = call_tool(self.client, "serial_set_mode", {"mode": "bridge"})
        self.assertEqual("bridge", result["mode"])
        self.assertIn(("agent_mode", "bridge"), self.hub.calls)

    def test_tool_list_has_no_port_discovery_or_binding_tools(self):
        names = self.list_tool_names()  # see the note below
        self.assertEqual(
            {"serial_status", "serial_exec", "serial_send", "serial_tail", "serial_set_mode"},
            set(names),
        )

    def test_exec_passes_raw_option(self):
        call_tool(self.client, "serial_exec", {"target": "linux", "cmd": "ls", "raw": True})
        options = [c for c in self.hub.calls if c[0] == "linux" and c[1] == "ls"][-1][2]
        self.assertTrue(options["raw"])
```

Note: if `test_mcp.py` has no tool-listing helper, add `list_tool_names` to the test class. It POSTs `{"jsonrpc":"2.0","id":1,"method":"tools/list"}` the same way `call_tool` posts `tools/call`, and returns `[tool["name"] for tool in body["result"]["tools"]]`.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_mcp.py -q -k "set_mode or raw_option or tool_list"`
Expected: FAIL (unknown tool / unexpected argument).

- [ ] **Step 3: Implement**

In `serial_bridge/mcp_server.py` add the `raw: bool = False` parameter after `exit_code` in `serial_exec` and `raw=raw` in the `ExecSpec(...)`. Replace the `serial_exec` docstring with:

```python
    """Run one text command through the Hub and capture its serial output (Echo and matched prompt removed). Returns status: completed (prompt or exit-code evidence; a nonzero exit_code is still completed), quiet or timeout (observation ended only; the command may still be running, do not resend automatically), disconnected (port lost, partial output kept), aborted, or error. completed does not mean asynchronous work such as an upgrade finished. Shell Targets: exit_code=true reports the remote exit status. Prompt-first consoles: prompt + prompt_settle_ms. Trim with grep (grep_invert drops matches) and max_lines (keeps the tail). raw=true also returns raw_base64: the first 32 KiB of the unmodified capture window (echo, ANSI, wrapper included) and raw_truncated."""
```

Add the new tool:

```python
async def serial_set_mode(mode: str) -> dict[str, Any]:
    """Switch the whole Hub to Bridge Mode or CRT Mode ('bridge' or 'crt'). Refused unless the Operator granted Mode Switch Permission (serial_status mode_switch.allowed) and refused while any Exec is in flight (busy_targets; nothing is queued). The result reports each Target's open outcome; Bridge Mode does not mean every port opened, so check ports and serial_status port_state. Port Bindings and port discovery stay with the Operator."""
    return await offload(_get_hub().set_mode_agent, mode)
```

Register it: `mcp.tool()(serial_set_mode)`, and update the `create_mcp` docstring to list it. Replace the `serial_status` docstring with:

```python
    """Return Hub mode, mode_switch {allowed, busy, busy_targets, next_action}, and each Target's Port Binding plus port_state (closed|open|lost), busy, shell (ready|unknown; ready only while the newest device output ends at the Operator-configured Target Prompt, otherwise unknown), shell_observed_at, and the current Session Log (`log` path on the Hub host; relative `log_url` for a Bearer GET from the same origin as /mcp). Empty log/log_url means none assigned. Use serial_tail for a Tail (last N lines). Do not pull the Session Log into serial_exec output."""
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add serial_bridge/mcp_server.py tests
git commit -m "feat: serial_set_mode tool and richer serial_exec/serial_status contract"
```

---

### Task 9: Operator Web UI

**Files:**
- Modify: `static/index.html` (near the mode hint, line ~43)
- Modify: `static/app.js` (`applyStatus` at ~346, `setMode` at ~1795)
- Test: `tests/test_ground_station_exec_ui.py`

**Interfaces:**
- Consumes: `status.mode_switch.allowed`, `status.ports[k].target_prompt`, `port_state`, `open_error`, `POST /api/mode_switch_permission`, `POST /api/target_prompt`, `start_bridge` result `ports`/`all_open`.
- Produces DOM ids: `#agent-mode-switch` (checkbox), `#target-prompt-target` (select), `#target-prompt-input` (text), `#target-prompt-save` (button), `#target-prompt-note`.

- [ ] **Step 1: Write the failing tests** (the static-file style used at `tests/test_ground_station_exec_ui.py:2368`; add to `GroundStationExecUiTest`)

```python
    def test_index_has_agent_mode_switch_and_target_prompt_controls(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        for dom_id in (
            "agent-mode-switch",
            "target-prompt-target",
            "target-prompt-input",
            "target-prompt-save",
            "target-prompt-note",
        ):
            self.assertIn(f'id="{dom_id}"', html)

    def test_app_js_posts_permission_and_prompt_and_reports_open_failures(self):
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("/api/mode_switch_permission", js)
        self.assertIn("/api/target_prompt", js)
        self.assertIn("all_open", js)
        self.assertIn("mode_switch", js)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_ground_station_exec_ui.py -q -k "agent_mode_switch or permission_and_prompt"`
Expected: FAIL (ids/strings missing).

- [ ] **Step 3: Implement**

`static/index.html`, directly after the `#mode-hint` span:

```html
        <label class="agent-mode-switch">
          <input type="checkbox" id="agent-mode-switch" />
          Allow Agent to switch mode
        </label>
        <span class="target-prompt">
          <select id="target-prompt-target" aria-label="Target"></select>
          <input type="text" id="target-prompt-input" placeholder="Target prompt (regex), e.g. # $" />
          <button type="button" id="target-prompt-save">Save prompt</button>
          <span id="target-prompt-note"></span>
        </span>
```

`static/app.js`:

- Near the other element lookups, add `const agentSwitch = document.getElementById("agent-mode-switch");` and the four prompt elements.
- At the end of `applyStatus(s)` add:

```js
    if (s.mode_switch) agentSwitch.checked = !!s.mode_switch.allowed;
    const promptSelect = document.getElementById("target-prompt-target");
    const names = Object.keys(s.ports || {});
    if (promptSelect.options.length !== names.length ||
        names.some((n, i) => promptSelect.options[i].value !== n)) {
      promptSelect.replaceChildren(...names.map((n) => new Option(s.ports[n].title || n, n)));
    }
    const selected = s.ports && s.ports[promptSelect.value];
    const promptInput = document.getElementById("target-prompt-input");
    if (selected && document.activeElement !== promptInput) {
      promptInput.value = selected.target_prompt || "";
    }
```

- Handlers, registered once with the other `addEventListener` calls:

```js
  agentSwitch.addEventListener("change", async () => {
    const res = await fetch("/api/mode_switch_permission", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ allowed: agentSwitch.checked }),
    });
    applyStatus(await res.json());
  });

  document.getElementById("target-prompt-save").addEventListener("click", async () => {
    const note = document.getElementById("target-prompt-note");
    const res = await fetch("/api/target_prompt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        target: document.getElementById("target-prompt-target").value,
        pattern: document.getElementById("target-prompt-input").value,
      }),
    });
    const data = await res.json();
    note.textContent = data.ok ? "saved" : data.error || data.detail || "save failed";
    if (data.ok) applyStatus(data);
  });
```

- In `setMode`, after the `if (!data.ok) {...}` block add:

```js
    if (data.ok && data.all_open === false) {
      const failed = Object.entries(data.ports || {})
        .filter(([, port]) => !port.open)
        .map(([name, port]) => `${name}: ${port.error}`)
        .join("; ");
      setPill("Bridge Mode: some ports not open", "warn");
      appendLine(slotTargets[0], "---", `Not open - ${failed}`, "system", "");
    }
```

- [ ] **Step 4: Run tests and smoke-check**

Run: `python -m pytest tests -q`
Expected: PASS. Then start the Hub (`python app.py`), open `http://127.0.0.1:8765/`, toggle "Allow Agent to switch mode" and confirm `GET /api/status` shows `mode_switch.allowed` flipping; save an invalid regex `(` and confirm the note shows the error.

- [ ] **Step 5: Commit**

```bash
git add static tests/test_ground_station_exec_ui.py
git commit -m "feat: Operator controls for Agent mode switching and Target Prompt"
```

---

### Task 10: Docs and final verification

**Files:**
- Modify: `CONTEXT.md` (Target Prompt wording)
- Modify: `README.md` (MCP tool list)
- Verify: whole suite

- [ ] **Step 1: Align `CONTEXT.md`**

In the **Target Prompt** entry replace "(literal or regular expression)" with "(a regular expression)". Do not change other terms.

- [ ] **Step 2: Update README**

Run `rg -n "serial_tail|serial_send" README.md`; in the MCP tools list add `serial_set_mode(mode)` with the permission/busy semantics, and add `status`, `raw`, `port_state`, `shell` to the existing Exec/status descriptions. Keep the README's existing style.

- [ ] **Step 3: Full verification**

Run: `python -m pytest tests -q`
Expected: all PASS, no new warnings.

Run: `rg -n "ports/|list_ports|serial_list|serial_bind" serial_bridge/mcp_server.py`
Expected: no matches (no MCP port discovery or binding tool).

Run: `rg -n "mode_switch_permission|target_prompt|/api/mode" serial_bridge/operator.py`
Expected: each route declared with `dependencies=[Depends(_require_operator_access)]`.

- [ ] **Step 4: Commit**

```bash
git add CONTEXT.md README.md
git commit -m "docs: document Agent mode switching, Exec Status, Port State"
```

---

## Self-Review

**Spec coverage:** `serial_set_mode` + permission + busy + atomicity + in-memory + revoke semantics: Task 7, 8. `mode_switch` with separate busy vs not-allowed `next_action`: Task 7. Per-Target open results, no rollback, all-failed reporting, Operator path consistent: Task 4 (shared `start_bridge`). Operator-only ports/Binding preserved: Global Constraints and Task 10 verification. Raw Capture: Task 2. Exec Status six values, nonzero exit still completed, quiet/timeout caveats: Task 1, docstring in Task 8. Disconnect broadcast, wake in-flight/queued Exec, partial data, Bridge Mode kept, completed Exec untouched: Task 3. Target Prompt (invalid regex rejected, change clears readiness, per-Exec `prompt` doesn't affect it): Task 5, 6. Shell Readiness freshness events and unknown default, `shell_observed_at`, no probes: Task 6. UI: Task 9.

**Assumptions to confirm during review:**
- "Busy" uses `worker.is_busy` (includes Operator writes and queued Agent Execs), the conservative reading of "in-flight Exec".
- `start_bridge` returns `ok: True` with `all_open: false` on partial failure so `mode` stays authoritative; clients must read `ports`/`all_open`.
- Target Prompt is a regular expression, persisted in `serial_bridge.json` under `target_prompts`, editable in either mode.
- `serial_set_mode` is not written to Agent Trace in this plan; add a trace kind separately if the Operator should see it there.

**Type consistency:** `status` values, `port_state`, `shell`, `mode_switch.next_action` strings, `abort_agents(disconnected=)`, `set_mode_agent`, `set_mode_switch_permission`, `set_target_prompt`, `observe_rx`, `clear_readiness`, `clear_all_readiness` are used with identical names across Tasks 1-9.
