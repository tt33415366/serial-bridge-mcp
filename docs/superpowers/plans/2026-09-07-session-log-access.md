# Session Log Reveal and Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the Operator reveal the current Session Log in the Hub host file manager from the footer, and let an Agent (or curl) download that same current file over HTTP with loopback-or-Bearer auth.

**Architecture:** Hub `status()` grows a per-Target relative `log_url`. `GET /api/session-log?target=` returns a FileResponse snapshot of the assigned Session Log (auth matches `POST /api/send`). `POST /api/session-log/reveal?target=` is loopback-only and launches the OS file manager at that file. Footer basenames become per-Target buttons that POST reveal; they do not navigate to `log_url`.

**Tech Stack:** Python 3.10+, FastAPI `FileResponse`, existing Operator auth helpers, unittest / `python -m pytest`, Ground Station `static/app.js` + node UI harness.

**Worktree:** `D:\SourceCode\serial_bridge\.worktrees\feature-session-log-access` on branch `feature/session-log-access`

## Global Constraints

- Domain words: **Session Log**, **Live Directory**, **Operator**, **Agent**, **Target**, **Hub**, **Target Name**. Do not call the Session Log “saved logs file”, “transcript”, or “tail”.
- Object is the **current** Session Log for one Target (the path Hub already stores on `ports[name]["log"]`), including after CRT until the next Bridge entry assigns new files. Not a Live Directory listing. Not historical Bridge sessions.
- One GET / one reveal = one Target Name. Reject `target=both`. Do not zip two files. Do not accept a filesystem path from the client.
- `log_url` is the relative string `/api/session-log?target=<TargetName>` when a Session Log is assigned, otherwise `""` (same emptiness rule as `log`).
- Download auth is `_require_send_access` (loopback **or** Bearer). Reveal auth is `_require_operator_access` (loopback **only**; Bearer must not open the Hub file manager).
- GET is a snapshot of the file bytes at request time. Do not follow/tail. Do not require CRT Mode.
- Missing assignment or missing file → HTTP 404 for GET and `{ok: false}` (no explorer) for reveal. Unknown Target Name → HTTP 400 with `resolve_target`’s error `detail`.
- Content-Disposition attachment filename is the Session Log basename. Media type `text/plain; charset=utf-8`.
- Footer: click a basename **only** POSTs reveal. Do not trigger download on click. Do not make the Live Directory path clickable.
- Do not add `serial_tail`. Do not grep Session Logs in the Hub. Do not put file contents in an MCP tool result. Do not make `GET /api/tail` authenticated as part of this work.
- Do not change Exec, Grep, Agent Trace, Port Binding, or mode switching.
- TDD for behavior changes: failing test first, then minimal code. Focused tests while iterating; full `python -m pytest -q` before each commit.
- Work only in this worktree/branch. Do not commit secrets (`serial_bridge.token`, `.env`).

---

## File map

- Modify: `serial_bridge/constants.py` — `SESSION_LOG_ROUTE`
- Modify: `serial_bridge/hub/core.py` — `log_url` on `status()`
- Modify: `serial_bridge/operator.py` — GET download, POST reveal, file-manager helper
- Modify: `tests/test_hub.py` — `log_url` on status before/after Bridge and after CRT
- Modify: `tests/test_app.py` — GET/POST HTTP tests
- Modify: `static/index.html` — footer Session Log container
- Modify: `static/app.js` — clickable per-Target basenames, POST reveal
- Modify: `static/style.css` — basename button chrome
- Modify: `tests/test_ground_station_exec_ui.py` — footer reveal scenario (reuse `run_ui_scenario`)
- Modify: `CONTEXT.md` — **Session Log** glossary term (if missing on this branch)
- Modify: `README.md` — reveal + authenticated download
- Create: `docs/adr/0028-session-log-reveal-and-download.md`

---

### Task 1: status() exposes relative log_url

**Files:**
- Modify: `serial_bridge/constants.py`
- Modify: `serial_bridge/hub/core.py`
- Modify: `tests/test_hub.py`
- Modify: `CONTEXT.md`
- Create: `docs/adr/0028-session-log-reveal-and-download.md`

**Interfaces:**
- Consumes: existing `Hub.status()`, `ports[name]["log"]` (Path or missing)
- Produces: `SESSION_LOG_ROUTE = "/api/session-log"` in `serial_bridge/constants.py`. Each `status()["ports"][name]` includes `log_url`: `f"{SESSION_LOG_ROUTE}?target={name}"` when `log` is assigned, else `""`. Downstream GET must use this exact route string.

- [ ] **Step 1: Write the failing tests**

In `tests/test_hub.py`, extend `LiveDirectoryTest.test_status_exposes_live_dir_and_empty_log_before_bridge` to also assert empty `log_url`:

```python
self.assertEqual("", status["ports"]["linux"]["log_url"])
self.assertEqual("", status["ports"]["rtos"]["log_url"])
```

In `test_bridge_creates_session_log_files_with_shared_timestamp`, after the existing `log` assertions:

```python
self.assertEqual(
    "/api/session-log?target=linux",
    status["ports"]["linux"]["log_url"],
)
self.assertEqual(
    "/api/session-log?target=rtos",
    status["ports"]["rtos"]["log_url"],
)
```

In `test_stop_bridge_retains_session_log_path`, after the retained `log` assertion:

```python
self.assertEqual(
    "/api/session-log?target=linux",
    hub.status()["ports"]["linux"]["log_url"],
)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_hub.py::LiveDirectoryTest::test_status_exposes_live_dir_and_empty_log_before_bridge tests/test_hub.py::LiveDirectoryTest::test_bridge_creates_session_log_files_with_shared_timestamp tests/test_hub.py::LiveDirectoryTest::test_stop_bridge_retains_session_log_path -v`

Expected: FAIL with KeyError `log_url` (or assertion on missing key).

- [ ] **Step 3: Write minimal implementation**

Add to `serial_bridge/constants.py`:

```python
HUB_PORT = 8765
SESSION_LOG_ROUTE = "/api/session-log"
```

In `serial_bridge/hub/core.py` `status()`, import `SESSION_LOG_ROUTE` and add `log_url` beside `log`:

```python
"log": str(v["log"]) if v.get("log") else "",
"log_url": (
    f"{SESSION_LOG_ROUTE}?target={k}" if v.get("log") else ""
),
```

If `CONTEXT.md` on this branch has no **Session Log** glossary term, insert it immediately after **Live Directory**:

```markdown
**Session Log**:
The complete on-disk record of one Target for one entry into Bridge Mode, written under the Live Directory as `<TargetName>-YYYY-MM-DD-HHMMSS.log`. The live transcript view and Exec output are bounded subsets of it, not replacements.
_Avoid_: saved logs file, log file (alone), transcript (the live view)
```

Write `docs/adr/0028-session-log-reveal-and-download.md` exactly:

```markdown
# Session Log reveal is loopback-only; download is a Bearer GET

The Operator opens the current Session Log by clicking its footer basename, which reveals the file in the Hub host file manager (loopback-only). Agents (and anyone with the Access Token) download that same current file via `GET /api/session-log?target=<TargetName>` (loopback or Bearer), advertised as a relative `log_url` on each Target in `serial_status`. Click does not download. Bearer cannot reveal. The GET is a snapshot of the file at request time, including after CRT until the next Bridge entry. Rejected: MCP `serial_tail`, returning the file in an MCP tool result, Hub-side Session Log Grep, unauthenticated whole-file GET (unlike `/api/tail`), remote Operator UI as the download client, and absolute Hub URLs in status.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_hub.py::LiveDirectoryTest -v`

Expected: PASS

- [ ] **Step 5: Full suite and commit**

Run: `python -m pytest -q`

Expected: PASS

```bash
git add serial_bridge/constants.py serial_bridge/hub/core.py tests/test_hub.py CONTEXT.md docs/adr/0028-session-log-reveal-and-download.md
git commit -m "Expose relative Session Log download URLs on Hub status."
```

---

### Task 2: GET current Session Log snapshot

**Files:**
- Modify: `serial_bridge/operator.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: `SESSION_LOG_ROUTE`, `_require_send_access`, `_resolve_target`, Hub `ports[name]["log"]` (Path | None)
- Produces: `GET /api/session-log?target=` → `FileResponse` of the assigned file when it exists. Auth: `_require_send_access`. Does not call reveal. Query param `target` is required (FastAPI default missing → 422).

- [ ] **Step 1: Write the failing tests**

Add class `SessionLogDownloadTest` to `tests/test_app.py`, with the same `setUp`/`tearDown` token-store pattern as `AppSendTest`. Put a real file on `FakeHub.ports["linux"]["log"]`.

```python
class SessionLogDownloadTest(unittest.TestCase):
    def setUp(self):
        self.token_temp_dir = tempfile.TemporaryDirectory()
        init_token_store(
            config_path=Path(self.token_temp_dir.name) / "serial_bridge.json",
            environ={},
        )
        self.files = tempfile.TemporaryDirectory()
        self.log_path = Path(self.files.name) / "linux-2026-08-18-093045.log"
        self.log_path.write_text("first snapshot\n", encoding="utf-8")
        self.fake_hub = FakeHub()
        self.fake_hub.ports["linux"]["log"] = self.log_path

    def tearDown(self):
        reset_token_store()
        self.token_temp_dir.cleanup()
        self.files.cleanup()

    def test_loopback_download_returns_file_snapshot(self):
        client = TestClient(app_module.app, client=("127.0.0.1", 50000))
        with patch.object(app_module, "hub", self.fake_hub):
            response = client.get("/api/session-log?target=linux")
        self.assertEqual(200, response.status_code)
        self.assertEqual(b"first snapshot\n", response.content)
        self.assertIn("text/plain", response.headers["content-type"])
        disposition = response.headers["content-disposition"]
        self.assertIn("attachment", disposition)
        self.assertIn("linux-2026-08-18-093045.log", disposition)

    def test_download_is_a_snapshot_not_a_follow(self):
        client = TestClient(app_module.app, client=("127.0.0.1", 50000))
        with patch.object(app_module, "hub", self.fake_hub):
            first = client.get("/api/session-log?target=linux")
            self.log_path.write_text("first snapshot\nlater line\n", encoding="utf-8")
            second = client.get("/api/session-log?target=linux")
        self.assertEqual(b"first snapshot\n", first.content)
        self.assertEqual(b"first snapshot\nlater line\n", second.content)

    def test_non_loopback_download_without_token_returns_401(self):
        client = TestClient(app_module.app, client=("192.0.2.10", 50000))
        with (
            patch.object(app_module, "hub", self.fake_hub),
            patch.dict("os.environ", {"SERIAL_BRIDGE_TOKEN": "secret"}, clear=False),
        ):
            response = client.get("/api/session-log?target=linux")
        self.assertEqual(401, response.status_code)
        self.assertEqual("Bearer", response.headers["www-authenticate"])

    def test_non_loopback_download_with_bearer_returns_file(self):
        client = TestClient(app_module.app, client=("192.0.2.10", 50000))
        with (
            patch.object(app_module, "hub", self.fake_hub),
            patch.dict("os.environ", {"SERIAL_BRIDGE_TOKEN": "secret"}, clear=False),
        ):
            response = client.get(
                "/api/session-log?target=linux",
                headers={"Authorization": "Bearer secret"},
            )
        self.assertEqual(200, response.status_code)
        self.assertEqual(b"first snapshot\n", response.content)

    def test_download_unknown_target_returns_400(self):
        client = TestClient(app_module.app, client=("127.0.0.1", 50000))
        with patch.object(app_module, "hub", self.fake_hub):
            response = client.get("/api/session-log?target=both")
        self.assertEqual(400, response.status_code)
        self.assertIn("unknown target", response.json()["detail"])

    def test_download_without_assigned_log_returns_404(self):
        self.fake_hub.ports["linux"]["log"] = None
        client = TestClient(app_module.app, client=("127.0.0.1", 50000))
        with patch.object(app_module, "hub", self.fake_hub):
            response = client.get("/api/session-log?target=linux")
        self.assertEqual(404, response.status_code)

    def test_download_missing_file_returns_404(self):
        self.log_path.unlink()
        client = TestClient(app_module.app, client=("127.0.0.1", 50000))
        with patch.object(app_module, "hub", self.fake_hub):
            response = client.get("/api/session-log?target=linux")
        self.assertEqual(404, response.status_code)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_app.py::SessionLogDownloadTest -v`

Expected: FAIL (404 on the route, or collection error if the class is present but the app has no route).

- [ ] **Step 3: Write minimal implementation**

In `serial_bridge/operator.py`:

- Import `FileResponse`, `HTTPException`, `SESSION_LOG_ROUTE`.
- Helper (module-private):

```python
def _assigned_session_log(target: object) -> Path:
    target_name, error = _resolve_target(target)
    if error is not None:
        raise HTTPException(status_code=400, detail=error)
    path = _get_hub().ports[target_name].get("log")
    if not path or not Path(path).is_file():
        raise HTTPException(status_code=404, detail="no current Session Log")
    return Path(path)
```

- Route (use `SESSION_LOG_ROUTE` as the path, not a string literal duplicate):

```python
@app.get(SESSION_LOG_ROUTE, dependencies=[Depends(_require_send_access)])
async def api_session_log(target: str) -> FileResponse:
    path = _assigned_session_log(target)
    return FileResponse(
        path,
        media_type="text/plain; charset=utf-8",
        filename=path.name,
        content_disposition_type="attachment",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_app.py::SessionLogDownloadTest -v`

Expected: PASS

- [ ] **Step 5: Full suite and commit**

Run: `python -m pytest -q`

Expected: PASS

```bash
git add serial_bridge/operator.py tests/test_app.py
git commit -m "Serve the current Session Log as an authenticated file download."
```

---

### Task 3: loopback-only reveal in the file manager

**Files:**
- Modify: `serial_bridge/operator.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: `_assigned_session_log`, `_require_operator_access`, `SESSION_LOG_ROUTE`
- Produces: `POST {SESSION_LOG_ROUTE}/reveal?target=` → `{"ok": true}` after starting the OS file manager. Function `reveal_session_log(path: Path) -> None` in `operator.py` (test patches this or `subprocess.Popen`). Windows: `explorer` with `/select,{resolved}`. macOS: `open -R`. Other: `xdg-open` of the parent directory. Do not wait on the process. Bearer must still 403.

- [ ] **Step 1: Write the failing tests**

Add class `SessionLogRevealTest` in `tests/test_app.py` (same token + tempfile setup as Task 2, with an assigned log file).

```python
class SessionLogRevealTest(unittest.TestCase):
    def setUp(self):
        self.token_temp_dir = tempfile.TemporaryDirectory()
        init_token_store(
            config_path=Path(self.token_temp_dir.name) / "serial_bridge.json",
            environ={},
        )
        self.files = tempfile.TemporaryDirectory()
        self.log_path = Path(self.files.name) / "linux-2026-08-18-093045.log"
        self.log_path.write_text("body\n", encoding="utf-8")
        self.fake_hub = FakeHub()
        self.fake_hub.ports["linux"]["log"] = self.log_path

    def tearDown(self):
        reset_token_store()
        self.token_temp_dir.cleanup()
        self.files.cleanup()

    def test_loopback_reveal_selects_the_session_log(self):
        client = TestClient(app_module.app, client=("127.0.0.1", 50000))
        with (
            patch.object(app_module, "hub", self.fake_hub),
            patch.object(bridge_operator, "reveal_session_log") as reveal,
        ):
            response = client.post("/api/session-log/reveal?target=linux")
        self.assertEqual(200, response.status_code)
        self.assertEqual({"ok": True}, response.json())
        reveal.assert_called_once()
        revealed = reveal.call_args.args[0]
        self.assertEqual(self.log_path.resolve(), Path(revealed).resolve())

    def test_non_loopback_reveal_with_bearer_is_rejected(self):
        client = TestClient(app_module.app, client=("192.0.2.10", 50000))
        with (
            patch.object(app_module, "hub", self.fake_hub),
            patch.dict("os.environ", {"SERIAL_BRIDGE_TOKEN": "secret"}, clear=False),
            patch.object(bridge_operator, "reveal_session_log") as reveal,
        ):
            response = client.post(
                "/api/session-log/reveal?target=linux",
                headers={"Authorization": "Bearer secret"},
            )
        self.assertEqual(403, response.status_code)
        reveal.assert_not_called()

    def test_reveal_without_assigned_log_returns_404(self):
        self.fake_hub.ports["linux"]["log"] = None
        client = TestClient(app_module.app, client=("127.0.0.1", 50000))
        with (
            patch.object(app_module, "hub", self.fake_hub),
            patch.object(bridge_operator, "reveal_session_log") as reveal,
        ):
            response = client.post("/api/session-log/reveal?target=linux")
        self.assertEqual(404, response.status_code)
        reveal.assert_not_called()

    def test_reveal_session_log_uses_platform_file_manager(self):
        with patch.object(bridge_operator.subprocess, "Popen") as popen:
            with patch.object(bridge_operator.sys, "platform", "win32"):
                bridge_operator.reveal_session_log(self.log_path)
            popen.assert_called_once()
            args = popen.call_args.args[0]
            self.assertEqual("explorer", args[0])
            self.assertTrue(args[1].startswith("/select,"))
            self.assertIn(str(self.log_path.resolve()), args[1])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_app.py::SessionLogRevealTest -v`

Expected: FAIL (404 on the route / missing `reveal_session_log`).

- [ ] **Step 3: Write minimal implementation**

In `serial_bridge/operator.py` add `import subprocess` and `import sys`.

```python
def reveal_session_log(path: Path) -> None:
    resolved = path.resolve()
    if sys.platform == "win32":
        subprocess.Popen(["explorer", f"/select,{resolved}"])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(resolved)])
    else:
        subprocess.Popen(["xdg-open", str(resolved.parent)])
```

```python
@app.post(
    f"{SESSION_LOG_ROUTE}/reveal",
    dependencies=[Depends(_require_operator_access)],
)
async def api_reveal_session_log(target: str) -> dict[str, Any]:
    path = _assigned_session_log(target)
    reveal_session_log(path)
    return {"ok": True}
```

Reuse `_assigned_session_log` from Task 2 (same 400/404 behavior). If Task 2’s helper raises HTTPException, POST reveal will too — FastAPI will not JSON `{"ok": false}`; tests expect 404 status. That is required.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_app.py::SessionLogRevealTest tests/test_app.py::SessionLogDownloadTest -v`

Expected: PASS

- [ ] **Step 5: Full suite and commit**

Run: `python -m pytest -q`

Expected: PASS

```bash
git add serial_bridge/operator.py tests/test_app.py
git commit -m "Reveal the current Session Log in the host file manager from loopback."
```

---

### Task 4: Footer basename click reveals; README

**Files:**
- Modify: `static/index.html`
- Modify: `static/app.js`
- Modify: `static/style.css`
- Modify: `tests/test_ground_station_exec_ui.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `POST /api/session-log/reveal?target=` from Task 3; status `ports[name].log` (filesystem path, already used for basename)
- Produces: `#foot-session-logs` contains one `button.foot-session-log` per assigned Session Log, `data-target` = Target Name, label = basename. Click POSTs reveal. Empty assignment clears the container and hides `#foot-logs-label` as today.

- [ ] **Step 1: Write the failing UI test**

In `tests/test_ground_station_exec_ui.py`, add:

```python
    def test_footer_session_log_basename_posts_reveal(self):
        result = run_ui_scenario(
            """
  await nextTurn();
  send({
    type: "status",
    mode: "bridge",
    live_dir: "D:\\\\logs\\\\serial-bridge",
    ports: {
      linux: {
        name: "linux", title: "Linux", com: "COM8", baud: 115200,
        open: true, busy: false,
        log: "D:\\\\logs\\\\serial-bridge\\\\linux-2026-08-18-093045.log",
        log_url: "/api/session-log?target=linux",
      },
      rtos: {
        name: "rtos", title: "RTOS", com: "COM9", baud: 115200,
        open: true, busy: false,
        log: "D:\\\\logs\\\\serial-bridge\\\\rtos-2026-08-18-093045.log",
        log_url: "/api/session-log?target=rtos",
      },
    },
  });
  const host = document.getElementById("foot-session-logs");
  const labels = host.children.map((child) => child.textContent);
  const targets = host.children.map((child) => child.dataset.target);
  const tags = host.children.map((child) => child.tagName);
  host.children[0].dispatch("click");
  await nextTurn();
  return {
    labelHidden: document.getElementById("foot-logs-label").hidden,
    labels,
    targets,
    tags,
    fetchRequests,
  };
"""
        )
        self.assertFalse(result["labelHidden"])
        self.assertEqual(
            ["linux-2026-08-18-093045.log", "rtos-2026-08-18-093045.log"],
            result["labels"],
        )
        self.assertEqual(["linux", "rtos"], result["targets"])
        self.assertEqual(["BUTTON", "BUTTON"], result["tags"])
        reveal = [
            entry
            for entry in result["fetchRequests"]
            if str(entry.get("url", "")).startswith("/api/session-log/reveal")
        ]
        self.assertEqual(1, len(reveal))
        self.assertEqual("/api/session-log/reveal?target=linux", reveal[0]["url"])
        self.assertEqual("POST", (reveal[0].get("options") or {}).get("method"))
        self.assertFalse(
            any(
                str(entry.get("url", "")).startswith("/api/session-log?")
                for entry in result["fetchRequests"]
            )
        )
```

    def test_footer_hides_session_logs_when_unassigned(self):
        result = run_ui_scenario(
            """
  await nextTurn();
  send({
    type: "status",
    mode: "crt",
    live_dir: "D:\\\\logs\\\\serial-bridge",
    ports: {
      linux: {
        name: "linux", title: "Linux", com: "COM8", baud: 115200,
        open: false, busy: false, log: "", log_url: "",
      },
      rtos: {
        name: "rtos", title: "RTOS", com: "COM9", baud: 115200,
        open: false, busy: false, log: "", log_url: "",
      },
    },
  });
  const host = document.getElementById("foot-session-logs");
  return {
    labelHidden: document.getElementById("foot-logs-label").hidden,
    childCount: host.children.length,
  };
"""
        )
        self.assertTrue(result["labelHidden"])
        self.assertEqual(0, result["childCount"])

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ground_station_exec_ui.py::GroundStationExecUiTest::test_footer_session_log_basename_posts_reveal -v`

Expected: FAIL (children empty / no POST reveal; today the footer is a single text node).

- [ ] **Step 3: Write minimal implementation**

`static/index.html`: change `#foot-session-logs` from `<code>` to `<span id="foot-session-logs" class="foot-session-logs"></span>`.

`static/app.js` — replace `updateFooterLogs`:

```javascript
  function revealSessionLog(target) {
    fetch(`/api/session-log/reveal?target=${encodeURIComponent(target)}`, {
      method: "POST",
    }).catch(() => {});
  }

  function updateFooterLogs(s) {
    if (s.live_dir) footLiveDir.textContent = s.live_dir;
    footSessionLogs.textContent = "";
    const assigned = portEntries(s.ports).filter(([, binding]) => binding && binding.log);
    if (!assigned.length) {
      footLogsLabel.hidden = true;
      return;
    }
    footLogsLabel.hidden = false;
    assigned.forEach(([name, binding]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "foot-session-log";
      button.dataset.target = name;
      button.textContent = basename(binding.log);
      button.addEventListener("click", () => revealSessionLog(name));
      footSessionLogs.appendChild(button);
    });
  }
```

`static/style.css` — keep `.foot code` for `#foot-live-dir`. Add:

```css
.foot-session-logs {
  display: inline-flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
  overflow: hidden;
}

.foot-session-log {
  overflow: hidden;
  margin: 0;
  padding: 0;
  border: 0;
  background: none;
  color: var(--dim);
  font: 9px var(--mono);
  letter-spacing: inherit;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
}
```

README **Live Directory** section: after the sentence about the footer showing directory and filenames, add that the Operator clicks a current Session Log filename to reveal it in the host file manager (Hub host / loopback), and that `GET /api/session-log?target=<TargetName>` downloads the current file (loopback or `Authorization: Bearer`, advertised as `log_url` on `serial_status`). State that click does not download.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ground_station_exec_ui.py::GroundStationExecUiTest::test_footer_session_log_basename_posts_reveal tests/test_ground_station_exec_ui.py::GroundStationExecUiTest::test_footer_hides_session_logs_when_unassigned -v`

Expected: PASS. Buttons are the only children of `#foot-session-logs` (spacing is CSS `gap`, not text nodes).

- [ ] **Step 5: Full suite and commit**

Run: `python -m pytest -q`

Expected: PASS

```bash
git add static/index.html static/app.js static/style.css tests/test_ground_station_exec_ui.py README.md
git commit -m "Reveal the current Session Log when the Operator clicks the footer filename."
```
