# Serial Tail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Agents a Tail of the current Session Log through MCP `serial_tail`, and remove unauthenticated `GET /api/tail`.

**Architecture:** Hub grows `tail(target, n)` that enforces one Target Name, `n` in 1–200, and the `{ok, target, tail, n}` contract. MCP `serial_tail` offloads that method. `get_tail` stays as the file-slice helper. Task 2 deletes the HTTP door.

**Tech Stack:** Python 3.10+, FastMCP, unittest / `python -m pytest`.

**Worktree:** `D:\SourceCode\serial_bridge\.worktrees\feature-serial-tail` on branch `feature/serial-tail`

## Global Constraints

- Domain words: **Tail**, **Session Log**, **Live Directory**, **Operator**, **Agent**, **Target**, **Hub**, **Target Name**. Do not call Tail “Follow”, “transcript”, or the whole Session Log.
- Tail is a bounded snapshot of the last N lines of the **current** Session Log for one Target. Not Follow. Not historical Bridge files. Not Hub-side Session Log Grep.
- Object is the assigned Session Log path (`ports[name]["log"]`), including after CRT until the next Bridge entry.
- MCP tool `serial_tail(target, n=80)` returns `{ok, target, tail, n}`. `tail` is at most N Session Log file lines joined with `"\n"`. `n` in the result is the cap used this call, not the number of lines returned.
- `n` defaults to 80. Reject `n < 1` or `n > 200` with `ok: false` (do not clip). No second byte cap. No `truncated` when the file is longer than `n`.
- One Target Name required (`resolve_target`). `both` is an unknown Target.
- Unknown Target, missing assignment, or missing file → `ok: false` + `error`. Assigned empty file → `ok: true`, `tail` `""`.
- Error for missing assignment/file: `"no current Session Log"`. Error for bad `n`: `"n must be an integer from 1 to 200"`. Unknown Target uses `resolve_target`’s existing `error`.
- Whole file stays on `log_url` / `GET /api/session-log`. Do not put the whole Session Log in an MCP tool result. Do not add `tail_url`.
- Tail does not write the serial port, does not take the queue, and does not wait for new lines.
- TDD for behavior changes: failing test first, then minimal code. Focused tests while iterating; full `python -m pytest -q` before each commit.
- Work only in this worktree/branch. Do not commit secrets (`serial_bridge.token`, `.env`).

---

## File map

- Modify: `serial_bridge/constants.py` — `TAIL_DEFAULT_N`, `TAIL_MAX_N`
- Modify: `serial_bridge/hub/core.py` — `Hub.tail`
- Modify: `serial_bridge/mcp_server.py` — `serial_tail` tool + `serial_status` docstring
- Modify: `tests/conftest.py` — `FakeHub.tail`
- Modify: `tests/test_hub.py` — Hub Tail contract tests
- Modify: `tests/test_mcp.py` — MCP tool tests; flip “no serial_tail” assertions
- Modify: `CONTEXT.md` — **Tail** glossary (if missing on this branch)
- Modify: `README.md` — `serial_tail` in MCP section
- Create: `docs/adr/0029-serial-tail-mcp-not-http.md`
- Modify (Task 2): `serial_bridge/operator.py` — delete `GET /api/tail`
- Modify (Task 2): `tests/test_app.py` — delete `/api/tail` tests

---

### Task 1: Add MCP `serial_tail`

**Files:**
- Modify: `serial_bridge/constants.py`
- Modify: `serial_bridge/hub/core.py`
- Modify: `serial_bridge/mcp_server.py`
- Modify: `tests/conftest.py`
- Modify: `tests/test_hub.py`
- Modify: `tests/test_mcp.py`
- Modify: `CONTEXT.md`
- Modify: `README.md`
- Create: `docs/adr/0029-serial-tail-mcp-not-http.md`

**Interfaces:**
- Consumes: `Hub.resolve_target`, `Hub.get_tail(target, n) -> dict[str, str]`, `ports[name]["log"]`, existing MCP Bearer auth
- Produces: `TAIL_DEFAULT_N = 80`, `TAIL_MAX_N = 200` in `serial_bridge/constants.py`. `Hub.tail(target: str, n: int = TAIL_DEFAULT_N) -> dict[str, Any]` with keys `ok`, `target`, `tail`, `n`, and `error` only when `ok` is false. MCP tool `serial_tail(target: str, n: int = TAIL_DEFAULT_N)` offloads `hub.tail`. Task 2 does not change this contract.

- [ ] **Step 1: Write the failing Hub tests**

In `tests/test_hub.py`, add `from serial_bridge.constants import TAIL_DEFAULT_N, TAIL_MAX_N` if needed. Append class `HubSerialTailTest` after `HubTailTest` (keep existing `get_tail` tests; they still describe the helper).

```python
class HubSerialTailTest(unittest.TestCase):
    def test_tail_returns_last_n_lines_for_one_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log = Path(temp_dir) / "linux.log"
            log.write_text("\n".join(f"line{i}" for i in range(100)), encoding="utf-8")
            hub = Hub(make_config())
            hub.ports["linux"]["log"] = log

            result = hub.tail("linux", n=5)

        self.assertEqual(
            {
                "ok": True,
                "target": "linux",
                "tail": "\n".join(f"line{i}" for i in range(95, 100)),
                "n": 5,
            },
            result,
        )

    def test_tail_defaults_n_to_80(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log = Path(temp_dir) / "linux.log"
            log.write_text("\n".join(f"line{i}" for i in range(90)), encoding="utf-8")
            hub = Hub(make_config())
            hub.ports["linux"]["log"] = log

            result = hub.tail("linux")

        self.assertEqual(TAIL_DEFAULT_N, result["n"])
        self.assertEqual(
            "\n".join(f"line{i}" for i in range(10, 90)),
            result["tail"],
        )

    def test_tail_rejects_n_outside_1_to_200(self):
        hub = Hub(make_config())
        for bad in (0, 201, -1):
            result = hub.tail("linux", n=bad)
            self.assertFalse(result["ok"], bad)
            self.assertEqual("linux", result["target"])
            self.assertEqual("", result["tail"])
            self.assertEqual(bad, result["n"])
            self.assertEqual("n must be an integer from 1 to 200", result["error"])

    def test_tail_unknown_target_is_error(self):
        hub = Hub(make_config())
        result = hub.tail("both")
        self.assertFalse(result["ok"])
        self.assertEqual("both", result["target"])
        self.assertEqual("", result["tail"])
        self.assertEqual(TAIL_DEFAULT_N, result["n"])
        self.assertIn("unknown target", result["error"])

    def test_tail_missing_assignment_is_error(self):
        hub = Hub(make_config())
        result = hub.tail("linux")
        self.assertEqual(
            {
                "ok": False,
                "target": "linux",
                "tail": "",
                "n": TAIL_DEFAULT_N,
                "error": "no current Session Log",
            },
            result,
        )

    def test_tail_missing_file_is_error(self):
        hub = Hub(make_config())
        hub.ports["linux"]["log"] = Path("missing-session.log")
        result = hub.tail("linux")
        self.assertFalse(result["ok"])
        self.assertEqual("no current Session Log", result["error"])

    def test_tail_empty_assigned_file_is_success(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log = Path(temp_dir) / "linux.log"
            log.write_text("", encoding="utf-8")
            hub = Hub(make_config())
            hub.ports["linux"]["log"] = log

            result = hub.tail("linux")

        self.assertEqual(
            {
                "ok": True,
                "target": "linux",
                "tail": "",
                "n": TAIL_DEFAULT_N,
            },
            result,
        )

    def test_tail_reads_assigned_log_after_crt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            live = Path(temp_dir)
            hub = Hub(make_config(live / "serial_bridge.json", live_dir=live))
            hub.start_bridge()
            log = Path(hub.ports["linux"]["log"])
            log.write_text("kept after crt\n", encoding="utf-8")
            hub.stop_bridge()

            result = hub.tail("linux")

        self.assertTrue(result["ok"])
        self.assertEqual("kept after crt", result["tail"])
        self.assertEqual(str(log), str(hub.ports["linux"]["log"]))
```

- [ ] **Step 2: Run Hub tests to verify they fail**

Run: `python -m pytest tests/test_hub.py::HubSerialTailTest -v`

Expected: FAIL (AttributeError `tail` or ImportError `TAIL_DEFAULT_N`).

- [ ] **Step 3: Write Hub `tail`**

Add to `serial_bridge/constants.py`:

```python
HUB_PORT = 8765
SESSION_LOG_ROUTE = "/api/session-log"
TAIL_DEFAULT_N = 80
TAIL_MAX_N = 200
```

In `serial_bridge/hub/core.py`, import `TAIL_DEFAULT_N` and `TAIL_MAX_N` from `serial_bridge.constants` (with existing `SESSION_LOG_ROUTE` import if present; add the import if `status()` already imports `SESSION_LOG_ROUTE` from there).

Add `Hub.tail` next to `get_tail`:

```python
    def tail(self, target: str, n: int = TAIL_DEFAULT_N) -> dict[str, Any]:
        target_name, error = self.resolve_target(target)
        resolved = target_name or ""
        if not isinstance(n, int) or isinstance(n, bool) or n < 1 or n > TAIL_MAX_N:
            echoed = n if isinstance(n, int) and not isinstance(n, bool) else TAIL_DEFAULT_N
            return {
                "ok": False,
                "target": resolved,
                "tail": "",
                "n": echoed,
                "error": f"n must be an integer from 1 to {TAIL_MAX_N}",
            }
        if error is not None:
            return {
                "ok": False,
                "target": resolved,
                "tail": "",
                "n": n,
                "error": error,
            }
        path = self.ports[target_name].get("log")
        if not path or not Path(path).is_file():
            return {
                "ok": False,
                "target": target_name,
                "tail": "",
                "n": n,
                "error": "no current Session Log",
            }
        return {
            "ok": True,
            "target": target_name,
            "tail": self.get_tail(target=target_name, n=n)[target_name],
            "n": n,
        }
```

Validate `n` before unknown-target so `n=0` on `"both"` reports the `n` error (tests call them separately). If a test would hit both, `n` wins.

- [ ] **Step 4: Run Hub tests to verify they pass**

Run: `python -m pytest tests/test_hub.py::HubSerialTailTest tests/test_hub.py::HubTailTest -v`

Expected: PASS

- [ ] **Step 5: Write the failing MCP tests**

In `tests/conftest.py`, add `FakeHub.tail` that records `self.calls` and implements the same contract as `Hub.tail` (resolve, `n` range, missing log error, empty file success) so MCP tests can use a real tempfile log or the fake. Prefer a thin fake that delegates to a real result shape:

```python
    def tail(self, target, n=80):
        from serial_bridge.constants import TAIL_DEFAULT_N, TAIL_MAX_N

        target_name, error = self.resolve_target(target)
        resolved = target_name or ""
        if not isinstance(n, int) or isinstance(n, bool) or n < 1 or n > TAIL_MAX_N:
            echoed = n if isinstance(n, int) and not isinstance(n, bool) else TAIL_DEFAULT_N
            result = {
                "ok": False,
                "target": resolved,
                "tail": "",
                "n": echoed,
                "error": f"n must be an integer from 1 to {TAIL_MAX_N}",
            }
            self.calls.append(("tail", target, n, result["ok"]))
            return result
        if error is not None:
            result = {
                "ok": False,
                "target": resolved,
                "tail": "",
                "n": n,
                "error": error,
            }
            self.calls.append(("tail", target, n, result["ok"]))
            return result
        log_path = self.ports[target_name].get("log")
        if not log_path or not Path(log_path).is_file():
            result = {
                "ok": False,
                "target": target_name,
                "tail": "",
                "n": n,
                "error": "no current Session Log",
            }
            self.calls.append(("tail", target, n, result["ok"]))
            return result
        lines = Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()
        result = {
            "ok": True,
            "target": target_name,
            "tail": "\n".join(lines[-n:]),
            "n": n,
        }
        self.calls.append(("tail", target, n, result["ok"]))
        return result
```

In `tests/test_mcp.py`:

- Update `test_mcp_tools_live_in_mcp_server_module` to `assertTrue(callable(mcp_server.serial_tail))`.
- Update `test_mcp_exposes_send_status_and_exec_tools` expected set to `{"serial_exec", "serial_send", "serial_status", "serial_tail"}`.
- In `test_serial_status_description_advertises_session_log_url`: keep Session Log / `log_url` / Bearer / `serial_exec` assertions; **replace** `assertNotIn("serial_tail", ...)` with `self.assertIn("serial_tail", {tool["name"] for tool in tools.values()})` and `self.assertIn("serial_tail", description)` (the `serial_status` docstring must name `serial_tail`).

Add:

```python
    def test_serial_tail_returns_last_n_lines(self):
        fake_hub = FakeHub()
        with tempfile.TemporaryDirectory() as temp_dir:
            log = Path(temp_dir) / "linux.log"
            log.write_text("a\nb\nc\n", encoding="utf-8")
            fake_hub.ports["linux"]["log"] = log
            with patch.object(app_module, "hub", fake_hub):
                response = call_tool(
                    self.client,
                    "serial_tail",
                    {"target": "linux", "n": 2},
                )

        result = response.json()["result"]["structuredContent"]
        self.assertEqual(
            {"ok": True, "target": "linux", "tail": "b\nc", "n": 2},
            result,
        )
        self.assertEqual(("tail", "linux", 2, True), fake_hub.calls[-1])

    def test_serial_tail_defaults_n_and_rejects_out_of_range(self):
        fake_hub = FakeHub()
        with tempfile.TemporaryDirectory() as temp_dir:
            log = Path(temp_dir) / "linux.log"
            log.write_text("only\n", encoding="utf-8")
            fake_hub.ports["linux"]["log"] = log
            with patch.object(app_module, "hub", fake_hub):
                defaulted = call_tool(
                    self.client, "serial_tail", {"target": "linux"}
                )
                bad = call_tool(
                    self.client,
                    "serial_tail",
                    {"target": "linux", "n": 201},
                )

        self.assertEqual(
            {"ok": True, "target": "linux", "tail": "only", "n": 80},
            defaulted.json()["result"]["structuredContent"],
        )
        rejected = bad.json()["result"]["structuredContent"]
        self.assertFalse(rejected["ok"])
        self.assertEqual("n must be an integer from 1 to 200", rejected["error"])
        self.assertEqual(201, rejected["n"])

    def test_serial_tail_unknown_target_and_missing_log(self):
        fake_hub = FakeHub()
        with patch.object(app_module, "hub", fake_hub):
            unknown = call_tool(
                self.client, "serial_tail", {"target": "both"}
            )
            missing = call_tool(
                self.client, "serial_tail", {"target": "linux"}
            )

        unknown_result = unknown.json()["result"]["structuredContent"]
        self.assertFalse(unknown_result["ok"])
        self.assertIn("unknown target", unknown_result["error"])
        self.assertEqual(
            {
                "ok": False,
                "target": "linux",
                "tail": "",
                "n": 80,
                "error": "no current Session Log",
            },
            missing.json()["result"]["structuredContent"],
        )
```

- [ ] **Step 6: Run MCP tests to verify they fail**

Run: `python -m pytest tests/test_mcp.py::McpHttpTest::test_serial_tail_returns_last_n_lines tests/test_mcp.py::McpHttpTest::test_mcp_exposes_send_status_and_exec_tools -v`

Expected: FAIL (tool missing / set mismatch).

- [ ] **Step 7: Write `serial_tail` and docs**

In `serial_bridge/mcp_server.py`:

```python
from serial_bridge.constants import TAIL_DEFAULT_N


async def serial_status() -> dict[str, Any]:
    """Return Hub mode and each Target's Port Binding, open/busy hints, and the current Session Log (`log` filesystem path on the Hub host; relative `log_url` for a Bearer GET of that file from the same origin as /mcp). Empty log/log_url means none assigned. Use serial_tail for a Tail (last N lines). Do not pull the Session Log into serial_exec output."""
    return await offload(_get_hub().status)


async def serial_tail(
    target: str,
    n: int = TAIL_DEFAULT_N,
) -> dict[str, Any]:
    """Return a Tail of the current Session Log: last n lines (default 80, max 200) for one Target Name. The whole file is log_url from serial_status, not this tool."""
    return await offload(_get_hub().tail, target, n)
```

Register `mcp.tool()(serial_tail)` in `create_mcp`. Update `create_mcp`’s docstring to name all four tools.

If `CONTEXT.md` has no **Tail** term, insert it immediately after **Session Log**:

```markdown
**Tail**:
A bounded snapshot of the last N lines of the current Session Log.
_Avoid_: Follow (the Operator pane pin), session log (the whole file), transcript (the live view), live tail (English in Follow, not this term)
```

Update **Grep** `_Avoid_` to: `filter (vague), search (vague), Tail (the last-N Session Log snapshot), keyword (the contract is one pattern, like prompt)`.

Write `docs/adr/0029-serial-tail-mcp-not-http.md` exactly:

```markdown
# Tail is MCP `serial_tail`; `GET /api/tail` is removed

Agents read a Tail (last N lines of the current Session Log) through MCP `serial_tail`, which returns `{ok, target, tail, n}` in the tool result. `n` defaults to 80 and is rejected outside 1–200; one Target Name is required. This is the bounded exception to ADR 0028: whole-file bytes stay on `log_url`, last N may enter the MCP result. CRT keeps the assigned Session Log until the next Bridge entry. Unknown Target, missing assignment, or missing file is `ok: false`; an assigned empty file is success with an empty `tail`. Rejected: keeping or authenticating `GET /api/tail`, a `tail_url` on status, `target=both`, a second byte cap, `truncated` when the file is longer than `n`, Hub-side Session Log Grep, and putting the whole Session Log in an MCP tool result. Supersedes the Tail deferral in ADR 0005.
```

README **MCP** list: after `serial_send`, add a `serial_tail` bullet: one Target; last `n` lines of the current Session Log (default 80, max 200); result `{ok, target, tail, n}`; whole file remains `log_url`. In the `serial_status` bullet, add that last N lines are `serial_tail`, not Exec output.

Do **not** delete `GET /api/tail` in this task.

- [ ] **Step 8: Run MCP tests to verify they pass**

Run: `python -m pytest tests/test_mcp.py::McpHttpTest -v`

Expected: PASS

- [ ] **Step 9: Full suite and commit**

Run: `python -m pytest -q`

Expected: PASS

```bash
git add serial_bridge/constants.py serial_bridge/hub/core.py serial_bridge/mcp_server.py tests/conftest.py tests/test_hub.py tests/test_mcp.py CONTEXT.md README.md docs/adr/0029-serial-tail-mcp-not-http.md docs/superpowers/plans/2026-09-07-serial-tail.md
git commit -m "Add MCP serial_tail for a bounded Session Log Tail."
```

---

### Task 2: Remove `GET /api/tail`

**Files:**
- Modify: `serial_bridge/operator.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: Task 1 `Hub.tail` / `serial_tail` (unchanged). `Hub.get_tail` may remain as the file-slice helper used by `Hub.tail`.
- Produces: no `GET /api/tail` route. Existing `GET /api/session-log` unchanged.

- [ ] **Step 1: Write the failing HTTP tests**

In `tests/test_app.py`, **replace** `test_api_tail_delegates_to_hub_get_tail` and `test_tail_returns_empty_lines_when_log_is_none` with:

```python
    def test_api_tail_route_is_removed(self):
        client = TestClient(app_module.app, client=("127.0.0.1", 50000))
        response = client.get("/api/tail?target=linux&n=10")
        self.assertEqual(404, response.status_code)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_app.py::AppSendTest::test_api_tail_route_is_removed -v`

If those tests are not on `AppSendTest`, use the class that currently owns `test_api_tail_delegates_to_hub_get_tail`. Expected: FAIL (200 instead of 404).

- [ ] **Step 3: Delete the route**

In `serial_bridge/operator.py`, delete the entire `api_tail` handler:

```python
    @app.get("/api/tail")
    async def api_tail(target: str = "both", n: int = 80) -> dict[str, Any]:
        return {"ok": True, "lines": _get_hub().get_tail(target, n)}
```

Do not delete `Hub.get_tail` or `Transcript.get_tail`. Do not change `serial_tail`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_app.py::AppSendTest::test_api_tail_route_is_removed tests/test_mcp.py::McpHttpTest::test_serial_tail_returns_last_n_lines -v`

Expected: PASS (adjust the HTTP class name if Step 1 used a different class).

- [ ] **Step 5: Full suite and commit**

Run: `python -m pytest -q`

Expected: PASS

```bash
git add serial_bridge/operator.py tests/test_app.py
git commit -m "Remove unauthenticated GET /api/tail."
```
