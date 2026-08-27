import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "static" / "app.js"
TRANSCRIPT_VIEW_JS = ROOT / "static" / "transcript_view.js"


def run_ui_scenario(scenario: str, agent_log_entries=None, local_storage=None):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not available")
    agent_log_entries = agent_log_entries or []
    local_storage = local_storage or {}
    script = f"""
const fs = require("fs");

(async () => {{
class FakeClassList {{
  constructor(owner) {{
    this.owner = owner;
    this.values = new Set();
  }}
  add(...names) {{
    for (const token of String(this.owner.className || "").split(/\\s+/)) {{
      if (token) this.values.add(token);
    }}
    names.forEach((name) => this.values.add(name));
    this.owner.className = [...this.values].join(" ");
  }}
  remove(...names) {{
    for (const token of String(this.owner.className || "").split(/\\s+/)) {{
      if (token) this.values.add(token);
    }}
    names.forEach((name) => this.values.delete(name));
    this.owner.className = [...this.values].join(" ");
  }}
  toggle(name, force) {{
    for (const token of String(this.owner.className || "").split(/\\s+/)) {{
      if (token) this.values.add(token);
    }}
    const enabled = force === undefined ? !this.values.has(name) : force;
    if (enabled) this.values.add(name);
    else this.values.delete(name);
    this.owner.className = [...this.values].join(" ");
    return enabled;
  }}
  contains(name) {{
    return String(this.owner.className || "").split(/\\s+/).includes(name) || this.values.has(name);
  }}
}}

globalThis.layoutReads = 0;
globalThis.rowLayoutReads = 0;
globalThis.childrenReads = 0;

class FakeElement {{
  constructor(id = "") {{
    this.id = id;
    this.tagName = "DIV";
    // Only the panes and other looked-up elements model the scroll geometry the app
    // reads once per frame; rows created by the app are measured separately and must
    // not inflate layoutReads-based assertions.
    this.tracksLayoutReads = Boolean(id);
    this._children = [];
    this._scrollHeight = null;
    this.dataset = {{}};
    this.className = "";
    this.classList = new FakeClassList(this);
    this.title = "";
    this.value = "";
    this.disabled = false;
    this.hidden = false;
    this.clientHeight = 0;
    this._scrollTop = 0;
    this.scrolledIntoView = false;
    this.scrollIntoViewOptions = null;
    this.parentNode = null;
    this._textContent = "";
    this.attributes = {{}};
    this.listeners = {{}};
  }}
  get children() {{
    globalThis.childrenReads += 1;
    return this._children;
  }}
  get textContent() {{
    return this._textContent + this._children.map((child) => child.textContent || "").join("");
  }}
  set textContent(value) {{
    this._textContent = String(value);
    this._children = [];
  }}
  set innerHTML(value) {{
    this.textContent = value;
  }}
  get childElementCount() {{
    return this._children.length;
  }}
  get firstElementChild() {{
    return this._children[0] || null;
  }}
  get nextElementSibling() {{
    const parent = this.parentNode;
    if (!parent) return null;
    return parent._children[parent._children.indexOf(this) + 1] || null;
  }}
  get scrollTop() {{
    return this._scrollTop;
  }}
  // Mirrors real-browser clamping to [0, scrollHeight - clientHeight]. Reads the
  // underlying scrollHeight value directly (not the public getter) so clamping does not
  // itself count as an extra layout read against layoutReads-based assertions.
  set scrollTop(value) {{
    const rawScrollHeight = this._scrollHeight === null ? this._children.length : this._scrollHeight;
    const max = Math.max(0, rawScrollHeight - this.clientHeight);
    this._scrollTop = Math.min(Math.max(0, Number(value) || 0), max);
  }}
  get scrollHeight() {{
    if (this.tracksLayoutReads) globalThis.layoutReads += 1;
    else globalThis.rowLayoutReads += 1;
    return this._scrollHeight === null ? this._children.length : this._scrollHeight;
  }}
  set scrollHeight(value) {{
    this._scrollHeight = Number(value);
  }}
  appendChild(child) {{
    if (child && typeof child === "object") child.parentNode = this;
    this._children.push(child);
    return child;
  }}
  insertBefore(child, reference) {{
    if (child && typeof child === "object") child.parentNode = this;
    const index = reference ? this._children.indexOf(reference) : -1;
    if (index < 0) this._children.push(child);
    else this._children.splice(index, 0, child);
    return child;
  }}
  append(...children) {{
    children.forEach((child) => this.appendChild(child));
  }}
  removeChild(child) {{
    this._children.splice(this._children.indexOf(child), 1);
    if (child) child.parentNode = null;
  }}
  addEventListener(type, listener) {{
    this.listeners[type] = this.listeners[type] || [];
    this.listeners[type].push(listener);
  }}
  dispatch(type, event = {{}}) {{
    for (const listener of this.listeners[type] || []) listener(event);
  }}
  querySelector() {{
    return new FakeElement();
  }}
  setAttribute(name, value) {{
    this.attributes[name] = String(value);
    if (name === "class") this.className = String(value);
  }}
  getAttribute(name) {{
    if (Object.prototype.hasOwnProperty.call(this.attributes, name)) return this.attributes[name];
    return name === "data-slot" ? "0" : null;
  }}
  scrollIntoView(options) {{
    this.scrolledIntoView = true;
    this.scrollIntoViewOptions = options || null;
  }}
  focus() {{}}
  setSelectionRange() {{}}
}}

const ids = new Map();
ids.set("holder-slot0", new FakeElement("holder-slot0"));
ids.set("holder-slot1", new FakeElement("holder-slot1"));
for (const id of ["holder-slot0", "holder-slot1"]) {{
  ids.get(id).className = "holder idle";
  ids.get(id).textContent = "IDLE";
}}
globalThis.document = {{
  getElementById(id) {{
    if (!ids.has(id)) ids.set(id, new FakeElement(id));
    return ids.get(id);
  }},
  createElement(tag) {{
    const element = new FakeElement();
    element.tagName = String(tag || "div").toUpperCase();
    // A freshly created row is not overflowed until a scenario says so.
    element.scrollHeight = 0;
    return element;
  }},
  createTextNode(text) {{
    return {{ textContent: String(text) }};
  }},
  querySelectorAll() {{
    return [];
  }},
}};
globalThis.location = {{ protocol: "http:", host: "localhost" }};
globalThis.setTimeout = () => {{}};
globalThis.frameCallbacks = [];
globalThis.requestAnimationFrame = (callback) => frameCallbacks.push(callback);
const storage = new Map(Object.entries({json.dumps(local_storage)}));
globalThis.localStorage = {{
  getItem(key) {{
    return storage.has(key) ? storage.get(key) : null;
  }},
  setItem(key, value) {{
    storage.set(key, String(value));
  }},
  removeItem(key) {{
    storage.delete(key);
  }},
  clear() {{
    storage.clear();
  }},
  dump() {{
    return Object.fromEntries(storage.entries());
  }},
}};
globalThis.CommandHistory = {{}};
globalThis.AnsiRender = {{
  renderAnsi(element, text) {{
    element.appendChild(document.createTextNode(text));
  }},
}};
globalThis.agentLogEntries = {json.dumps(agent_log_entries)};
globalThis.fetchCalls = [];
globalThis.fetch = async (url) => {{
  fetchCalls.push(url);
  if (url === "/api/agent_log") {{
    return {{
      ok: true,
      json: async () => ({{ ok: true, entries: agentLogEntries }}),
    }};
  }}
  return {{
    ok: true,
    json: async () => ({{ ok: true }}),
  }};
}};
globalThis.WebSocket = class {{
  static OPEN = 1;
  constructor() {{
    this.readyState = WebSocket.OPEN;
    globalThis.socket = this;
  }}
  send() {{}}
}};

eval(fs.readFileSync({json.dumps(str(TRANSCRIPT_VIEW_JS))}, "utf8"));
// Hand the app instrumented panes so a scenario can read retained model depth, which the
// app deliberately does not expose to the page.
const createRealPane = globalThis.TranscriptView.createPane;
globalThis.paneModelSpies = [];
globalThis.TranscriptView.createPane = (budget) => {{
  const pane = createRealPane(budget);
  paneModelSpies.push(pane);
  return pane;
}};
eval(fs.readFileSync({json.dumps(str(APP_JS))}, "utf8"));
const send = (message) => socket.onmessage({{ data: JSON.stringify(message) }});
const term = (slot) => document.getElementById(`term-${{slot}}`);
const holder = (slot) => document.getElementById(`holder-${{slot}}`);
const nextTurn = () => new Promise((resolve) => setImmediate(resolve));
const flushFrames = () => {{
  frameCallbacks.splice(0).forEach((callback) => callback());
}};
const result = await (async () => {{
{scenario}
}})();
console.log(JSON.stringify(result));
}})();
"""
    completed = subprocess.run(
        [node, "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(completed.stdout.strip())


class GroundStationExecUiTest(unittest.TestCase):
    def test_exec_echo_is_not_recorded_as_send_and_precedes_capture(self):
        result = run_ui_scenario(
            """
  await nextTurn();
  send({
    type: "exec", phase: "start", id: 41, target: "linux",
    cmd: "uname -a", ts: "10:20:30.000",
  });
  send({
    type: "line", target: "linux", direction: ">>>", who: "agent",
    text: "uname -a", ts: "10:20:30.001",
  });
  send({
    type: "line", target: "linux", direction: "<<<",
    text: "Linux target", ts: "10:20:30.002",
  });
  send({
    type: "exec", phase: "end", id: 41, target: "linux",
    ended_by: "prompt", ms: 25, bytes: 12, truncated: false, ok: true,
  });
  const body = document.getElementById("spine-body");
  const rows = term("slot0").children;
  return {
    spineClasses: body.children.map((child) => child.className),
    tally: document.getElementById("spine-tally").textContent,
    termClasses: rows.map((child) => child.className),
    execIds: rows.map((child) => child.dataset.execId || ""),
    capturedText: rows[1].textContent,
  };
"""
        )

        self.assertEqual(["spine-node exec sealed"], result["spineClasses"])
        self.assertIn("send 0", result["tally"])
        self.assertEqual(
            ["ln agent", "ln dev capture-row cap-top cap-bot", "cap-foot"],
            result["termClasses"],
        )
        self.assertEqual(["", "41", "41"], result["execIds"])
        self.assertIn("Linux target", result["capturedText"])

    def test_spine_tracks_exec_and_agent_send_newest_first_with_tally(self):
        result = run_ui_scenario(
            """
  await nextTurn();
  send({
    type: "exec", phase: "start", id: 17, target: "linux",
    cmd: "cat /proc/meminfo", prompt: null, ts: "10:20:30.000",
  });
  send({
    type: "line", target: "rtos", direction: ">>>", who: "agent",
    text: "reboot", ts: "10:20:31.000",
  });
  send({
    type: "line", target: "rtos", direction: ">>>", who: "user",
    text: "status", ts: "10:20:32.000",
  });
  send({
    type: "exec", phase: "end", id: 17, target: "linux",
    ended_by: "abort", ms: 300, bytes: 2048, truncated: true, ok: false,
  });
  const body = document.getElementById("spine-body");
  return {
    classes: body.children.map((child) => child.className),
    texts: body.children.map((child) => child.textContent),
    tally: document.getElementById("spine-tally").textContent,
  };
"""
        )

        self.assertEqual(
            ["spine-node send", "spine-node exec sealed aborted capped"],
            result["classes"],
        )
        self.assertIn("reboot", result["texts"][0])
        self.assertIn("fire-and-forget", result["texts"][0])
        self.assertIn("cat /proc/meminfo", result["texts"][1])
        self.assertIn("aborted", result["texts"][1])
        self.assertIn("300 ms", result["texts"][1])
        self.assertIn("exec 1", result["tally"])
        self.assertIn("send 1", result["tally"])
        self.assertIn("aborted 1", result["tally"])
        self.assertIn("capped 1", result["tally"])
        self.assertIn("median 300 ms", result["tally"])

    def test_hydrate_replaces_spine_and_restores_running_holders(self):
        result = run_ui_scenario(
            """
  await nextTurn();
  const initial = {
    classes: document.getElementById("spine-body").children.map((child) => child.className),
    holder0: holder("slot0").textContent,
    holder1: holder("slot1").textContent,
  };
  send({
    type: "line", target: "linux", direction: ">>>", who: "agent",
    text: "temporary send", ts: "10:00:03.000",
  });
  agentLogEntries = [{
    id: 9, phase: "end", target: "rtos", cmd: "version", prompt: null,
    ts: "10:00:04.000", ended_by: "idle", ms: 100, bytes: 7,
    truncated: false, ok: true,
  }];
  await socket.onopen();
  const body = document.getElementById("spine-body");
  return {
    initial,
    reconnectClasses: body.children.map((child) => child.className),
    reconnectText: body.textContent,
    holder0: holder("slot0").textContent,
    holder1: holder("slot1").textContent,
    fetchCount: fetchCalls.filter((url) => url === "/api/agent_log").length,
  };
""",
            agent_log_entries=[
                {
                    "id": 8,
                    "phase": "start",
                    "target": "linux",
                    "cmd": "top",
                    "prompt": None,
                    "ts": "10:00:02.000",
                },
                {
                    "id": 7,
                    "phase": "end",
                    "target": "rtos",
                    "cmd": "help",
                    "prompt": None,
                    "ts": "10:00:01.000",
                    "ended_by": "prompt",
                    "ms": 200,
                    "bytes": 12,
                    "truncated": False,
                    "ok": True,
                },
            ],
        )

        self.assertEqual(
            ["spine-node exec running", "spine-node exec sealed"],
            result["initial"]["classes"],
        )
        self.assertEqual("AGENT EXEC", result["initial"]["holder0"])
        self.assertEqual("IDLE", result["initial"]["holder1"])
        self.assertEqual(["spine-node exec sealed"], result["reconnectClasses"])
        self.assertNotIn("temporary send", result["reconnectText"])
        self.assertEqual("IDLE", result["holder0"])
        self.assertEqual("IDLE", result["holder1"])
        self.assertGreaterEqual(result["fetchCount"], 2)

    def test_exec_capture_routes_only_device_lines_and_seals(self):
        result = run_ui_scenario(
            """
  send({ type: "exec", phase: "start", id: 17, target: "linux" });
  send({ type: "line", target: "linux", direction: ">>>", who: "agent", text: "run" });
  send({ type: "line", target: "linux", direction: "<<<", text: "device output" });
  send({ type: "line", target: "linux", direction: ">>>", who: "user", text: "barge" });
  send({
    type: "exec", phase: "end", id: 17, target: "linux",
    ended_by: "idle", ms: 1240, bytes: 3174, truncated: true, ok: true,
  });
  const rows = term("slot0").children;
  return {
    holderText: holder("slot0").textContent,
    holderClass: holder("slot0").className,
    termClasses: rows.map((child) => child.className),
    capturedText: rows[1].textContent,
    footText: rows[2].textContent,
  };
"""
        )

        self.assertEqual("IDLE", result["holderText"])
        self.assertEqual("holder idle", result["holderClass"])
        self.assertEqual(
            ["ln agent", "ln dev capture-row cap-top cap-bot", "cap-foot", "ln op"],
            result["termClasses"],
        )
        self.assertIn("device output", result["capturedText"])
        self.assertIn("1.24 s", result["footText"])
        self.assertIn("3.1 KiB", result["footText"])
        self.assertIn("closed on idle", result["footText"])
        self.assertIn("capped", result["footText"])

    def test_exec_start_lights_holder_and_abort_uses_abort_wording(self):
        result = run_ui_scenario(
            """
  send({ type: "exec", phase: "start", id: 8, target: "rtos" });
  const running = {
    text: holder("slot1").textContent,
    className: holder("slot1").className,
  };
  send({
    type: "exec", phase: "end", id: 8, target: "rtos",
    ended_by: "abort", ms: 80, bytes: 12, truncated: false, ok: false,
  });
  return {
    running,
    termChildren: term("slot1").children.length,
    endedText: holder("slot1").textContent,
  };
"""
        )

        self.assertEqual("AGENT EXEC", result["running"]["text"])
        self.assertEqual("holder agent", result["running"]["className"])
        self.assertEqual(0, result["termChildren"])
        self.assertEqual("IDLE", result["endedText"])

    def test_unknown_end_reason_renders_as_error_in_spine_and_capture(self):
        result = run_ui_scenario(
            """
  await nextTurn();
  send({ type: "exec", phase: "start", id: 18, target: "linux", cmd: "probe" });
  send({ type: "line", target: "linux", direction: "<<<", text: "output" });
  send({
    type: "exec", phase: "end", id: 18, target: "linux",
    ended_by: "mystery", ms: 10, bytes: 2, truncated: false, ok: false,
  });
  return {
    spineText: document.getElementById("spine-body").textContent,
    captureText: term("slot0").textContent,
  };
"""
        )

        self.assertIn("error", result["spineText"])
        self.assertNotIn("mystery", result["spineText"])
        self.assertIn("closed on error", result["captureText"])
        self.assertNotIn("mystery", result["captureText"])

    def test_live_view_budget_defaults_to_75k_for_missing_or_invalid_storage(self):
        for initial_storage in (
            {},
            {"serial-bridge-live-view-budget": "bogus"},
        ):
            with self.subTest(initial_storage=initial_storage):
                result = run_ui_scenario(
                    """
  const stop75 = document.getElementById("live-depth-75000");
  return {
    pressed75: stop75.getAttribute("aria-pressed"),
    class75: stop75.className,
    pressed500: document.getElementById("live-depth-500").getAttribute("aria-pressed"),
  };
""",
                    local_storage=initial_storage,
                )

                self.assertEqual("true", result["pressed75"])
                self.assertIn("active", result["class75"])
                self.assertEqual("false", result["pressed500"])

    def test_selecting_500_persists_marks_active_and_trims_both_panes(self):
        result = run_ui_scenario(
            """
  for (let index = 0; index < 505; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `linux-${index}` });
    send({ type: "line", target: "rtos", direction: "<<<", text: `rtos-${index}` });
  }
  document.getElementById("live-depth-500").dispatch("click");
  return {
    stored: localStorage.dump()["serial-bridge-live-view-budget"],
    pressed500: document.getElementById("live-depth-500").getAttribute("aria-pressed"),
    class500: document.getElementById("live-depth-500").className,
    pressed75: document.getElementById("live-depth-75000").getAttribute("aria-pressed"),
    rows0: term("slot0").children.length,
    rows1: term("slot1").children.length,
    retained0: paneModelSpies[0].countedSize(),
    retained1: paneModelSpies[1].countedSize(),
    text0: term("slot0").textContent,
    text1: term("slot1").textContent,
  };
"""
        )

        self.assertEqual("500", result["stored"])
        self.assertEqual("true", result["pressed500"])
        self.assertIn("active", result["class500"])
        self.assertEqual("false", result["pressed75"])
        self.assertEqual(240, result["rows0"])
        self.assertEqual(240, result["rows1"])
        self.assertEqual(500, result["retained0"])
        self.assertEqual(500, result["retained1"])
        self.assertNotIn("linux-0", result["text0"])
        self.assertNotIn("rtos-0", result["text1"])
        self.assertIn("linux-504", result["text0"])
        self.assertIn("rtos-504", result["text1"])

    def test_selecting_5k_restores_5000_on_next_evaluation(self):
        selected = run_ui_scenario(
            """
  document.getElementById("live-depth-5000").dispatch("click");
  return { stored: localStorage.dump()["serial-bridge-live-view-budget"] };
"""
        )
        result = run_ui_scenario(
            """
  const stop5k = document.getElementById("live-depth-5000");
  return {
    pressed5k: stop5k.getAttribute("aria-pressed"),
    class5k: stop5k.className,
    pressed75: document.getElementById("live-depth-75000").getAttribute("aria-pressed"),
  };
""",
            local_storage={"serial-bridge-live-view-budget": selected["stored"]},
        )

        self.assertEqual("5000", selected["stored"])
        self.assertEqual("true", result["pressed5k"])
        self.assertIn("active", result["class5k"])
        self.assertEqual("false", result["pressed75"])

    def test_dynamic_budget_keeps_capture_accounting_without_scrollback_rescan(self):
        result = run_ui_scenario(
            """
  document.getElementById("live-depth-500").dispatch("click");
  send({ type: "exec", phase: "start", id: 71, target: "linux", cmd: "stream" });
  for (let index = 0; index < 500; index += 1) {
    send({
      type: "line", target: "linux", direction: "<<<",
      text: `line-${index}`,
    });
  }
  const before = childrenReads;
  for (let index = 0; index < 12; index += 1) {
    send({
      type: "line", target: "linux", direction: "<<<",
      text: `trim-${index}`,
    });
  }
  const trimmed = { scans: childrenReads - before };
  const rows = term("slot0").children;
  return {
    ...trimmed,
    termChildren: rows.length,
    captureRows: rows.filter((row) => row.classList.contains("capture-row")).length,
    tops: rows.filter((row) => row.classList.contains("cap-top")).length,
    text: term("slot0").textContent,
  };
"""
        )

        self.assertEqual(240, result["termChildren"])
        self.assertEqual(240, result["captureRows"])
        self.assertEqual(1, result["tops"])
        self.assertEqual(0, result["scans"])
        self.assertNotIn("line-0", result["text"])
        self.assertIn("trim-11", result["text"])

    def test_follow_detaches_per_pane_and_other_pane_keeps_rendering(self):
        result = run_ui_scenario(
            """
  const linux = term("slot0");
  const rtos = term("slot1");
  linux.clientHeight = 100;
  linux.scrollHeight = 200;
  linux.scrollTop = 60;
  linux.dispatch("scroll");
  rtos.clientHeight = 100;
  rtos.scrollHeight = 200;
  rtos.scrollTop = 68;
  rtos.dispatch("scroll");
  send({ type: "line", target: "linux", direction: "<<<", text: "linux-paused" });
  send({ type: "line", target: "rtos", direction: "<<<", text: "rtos-live" });
  return {
    linuxRows: linux.children.length,
    linuxText: linux.textContent,
    rtosRows: rtos.children.length,
    rtosText: rtos.textContent,
  };
"""
        )

        self.assertEqual(0, result["linuxRows"])
        self.assertNotIn("linux-paused", result["linuxText"])
        self.assertEqual(1, result["rtosRows"])
        self.assertIn("rtos-live", result["rtosText"])

    def test_follow_recovery_appends_gap_and_retained_tail_in_original_order(self):
        result = run_ui_scenario(
            """
  const linux = term("slot0");
  linux.clientHeight = 100;
  linux.scrollHeight = 200;
  linux.scrollTop = 40;
  linux.dispatch("scroll");
  for (let index = 0; index < 1001; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `omitted-${index}` });
  }
  const detached = { rows: linux.children.length, text: linux.textContent };
  linux.scrollTop = 100;
  linux.dispatch("scroll");
  return {
    detached,
    rows: linux.children.length,
    classes: linux.children.map((child) => child.className),
    texts: linux.children.map((child) => child.textContent),
    text: linux.textContent,
  };
"""
        )

        self.assertEqual(0, result["detached"]["rows"])
        self.assertNotIn("omitted-1000", result["detached"]["text"])
        self.assertEqual(33, result["rows"])
        self.assertEqual("ln gap", result["classes"][0])
        self.assertEqual(
            "— 969 lines in session log, not in this view —",
            result["texts"][0],
        )
        self.assertNotIn("omitted-968", result["text"])
        self.assertIn("omitted-969", result["texts"][1])
        self.assertIn("omitted-1000", result["texts"][-1])

    def test_detached_writes_and_system_rows_replay_when_follow_resumes(self):
        result = run_ui_scenario(
            """
  const linux = term("slot0");
  linux.clientHeight = 100;
  linux.scrollHeight = 200;
  linux.scrollTop = 40;
  linux.dispatch("scroll");
  send({
    type: "line", target: "linux", direction: ">>>", who: "agent",
    text: "paused-agent-write", ts: "10:00:00.001",
  });
  send({
    type: "line", target: "linux", direction: "---",
    text: "paused-system-row", ts: "10:00:00.002",
  });
  const detached = {
    rows: linux.children.length,
    text: linux.textContent,
  };
  linux.scrollTop = 100;
  linux.dispatch("scroll");
  return {
    detached,
    rows: linux.children.length,
    classes: linux.children.map((child) => child.className),
    texts: linux.children.map((child) => child.textContent),
  };
"""
        )

        self.assertEqual(0, result["detached"]["rows"])
        self.assertNotIn("paused-agent-write", result["detached"]["text"])
        self.assertNotIn("paused-system-row", result["detached"]["text"])
        self.assertEqual(2, result["rows"])
        self.assertEqual(["ln agent", "ln sys"], result["classes"])
        self.assertIn("paused-agent-write", result["texts"][0])
        self.assertIn("paused-system-row", result["texts"][1])

    def test_detached_write_replay_keeps_newest_200_and_counts_overflow_gap(self):
        result = run_ui_scenario(
            """
  const linux = term("slot0");
  linux.clientHeight = 100;
  linux.scrollHeight = 200;
  linux.scrollTop = 40;
  linux.dispatch("scroll");
  for (let index = 0; index < 201; index += 1) {
    send({
      type: "line", target: "linux", direction: ">>>", who: "user",
      text: `write-${index}`,
    });
  }
  linux.scrollTop = 100;
  linux.dispatch("scroll");
  return {
    rows: linux.children.length,
    texts: linux.children.map((child) => child.textContent),
    text: linux.textContent,
  };
"""
        )

        self.assertEqual(201, result["rows"])
        self.assertEqual(
            "— 1 lines in session log, not in this view —",
            result["texts"][0],
        )
        self.assertNotIn("write-0", result["text"])
        self.assertIn("write-1", result["texts"][1])
        self.assertIn("write-200", result["texts"][-1])

    def test_follow_recovery_replays_retained_writes_and_device_tail_by_timestamp(self):
        result = run_ui_scenario(
            """
  const linux = term("slot0");
  linux.clientHeight = 100;
  linux.scrollHeight = 200;
  linux.scrollTop = 40;
  linux.dispatch("scroll");
  send({
    type: "line", target: "linux", direction: ">>>", who: "agent",
    text: "agent-third", ts: "10:00:00.003",
  });
  send({
    type: "line", target: "linux", direction: "<<<",
    text: "device-first", ts: "10:00:00.001",
  });
  send({
    type: "line", target: "linux", direction: "---",
    text: "system-second", ts: "10:00:00.002",
  });
  send({
    type: "line", target: "linux", direction: "<<<",
    text: "device-fourth", ts: "10:00:00.004",
  });
  linux.scrollTop = 100;
  linux.dispatch("scroll");
  return {
    classes: linux.children.map((child) => child.className),
    texts: linux.children.map((child) => child.textContent),
  };
"""
        )

        self.assertEqual(["ln dev", "ln sys", "ln agent", "ln dev"], result["classes"])
        self.assertIn("device-first", result["texts"][0])
        self.assertIn("system-second", result["texts"][1])
        self.assertIn("agent-third", result["texts"][2])
        self.assertIn("device-fourth", result["texts"][3])

    def test_follow_recovery_preserves_arrival_order_for_equal_or_missing_timestamps(self):
        result = run_ui_scenario(
            """
  const linux = term("slot0");
  linux.clientHeight = 100;
  linux.scrollHeight = 200;
  linux.scrollTop = 40;
  linux.dispatch("scroll");
  send({ type: "line", target: "linux", direction: ">>>", who: "user", text: "missing-write" });
  send({ type: "line", target: "linux", direction: "<<<", text: "missing-device" });
  send({ type: "line", target: "linux", direction: "---", text: "missing-system" });
  linux.scrollTop = 100;
  linux.dispatch("scroll");
  const missing = linux.children.map((child) => child.textContent);

  document.getElementById("btn-clear").dispatch("click");
  linux.clientHeight = 100;
  linux.scrollHeight = 200;
  linux.scrollTop = 40;
  linux.dispatch("scroll");
  send({
    type: "line", target: "linux", direction: ">>>", who: "user",
    text: "equal-write", ts: "10:00:00.001",
  });
  send({
    type: "line", target: "linux", direction: "<<<",
    text: "equal-device", ts: "10:00:00.001",
  });
  send({
    type: "line", target: "linux", direction: "---",
    text: "equal-system", ts: "10:00:00.001",
  });
  linux.scrollTop = 100;
  linux.dispatch("scroll");
  return {
    missing,
    equal: linux.children.map((child) => child.textContent),
  };
"""
        )

        self.assertIn("missing-write", result["missing"][0])
        self.assertIn("missing-device", result["missing"][1])
        self.assertIn("missing-system", result["missing"][2])
        self.assertIn("equal-write", result["equal"][0])
        self.assertIn("equal-device", result["equal"][1])
        self.assertIn("equal-system", result["equal"][2])

    def test_follow_recovery_orders_mixed_missing_and_present_timestamps_consistently(self):
        result = run_ui_scenario(
            """
  const linux = term("slot0");
  linux.clientHeight = 100;
  linux.scrollHeight = 200;
  linux.scrollTop = 40;
  linux.dispatch("scroll");
  send({
    type: "line", target: "linux", direction: ">>>", who: "user",
    text: "write-latest", ts: "10:00:00.003",
  });
  send({ type: "line", target: "linux", direction: "<<<", text: "device-no-ts" });
  send({
    type: "line", target: "linux", direction: "---",
    text: "system-earliest", ts: "10:00:00.001",
  });
  linux.scrollTop = 100;
  linux.dispatch("scroll");
  return {
    texts: linux.children.map((child) => child.textContent),
  };
"""
        )

        self.assertIn("device-no-ts", result["texts"][0])
        self.assertIn("system-earliest", result["texts"][1])
        self.assertIn("write-latest", result["texts"][2])

    def test_delayed_agent_send_is_recorded_once_while_follow_is_paused(self):
        result = run_ui_scenario(
            """
  await nextTurn();
  const linux = term("slot0");
  linux.clientHeight = 100;
  linux.scrollHeight = 200;
  linux.scrollTop = 40;
  linux.dispatch("scroll");
  send({
    type: "line", target: "linux", direction: ">>>", who: "agent",
    text: "record-once", ts: "10:00:00.001",
  });
  const body = document.getElementById("spine-body");
  const detached = {
    rows: linux.children.length,
    spineCount: body.children.length,
    spineText: body.textContent,
    tally: document.getElementById("spine-tally").textContent,
  };
  linux.scrollTop = 100;
  linux.dispatch("scroll");
  return {
    detached,
    rows: linux.children.length,
    spineCount: body.children.length,
    spineText: body.textContent,
    tally: document.getElementById("spine-tally").textContent,
  };
"""
        )

        self.assertEqual(0, result["detached"]["rows"])
        self.assertEqual(1, result["detached"]["spineCount"])
        self.assertIn("record-once", result["detached"]["spineText"])
        self.assertIn("send 1", result["detached"]["tally"])
        self.assertEqual(1, result["rows"])
        self.assertEqual(1, result["spineCount"])
        self.assertIn("record-once", result["spineText"])
        self.assertIn("send 1", result["tally"])

    def test_trace_jump_for_detached_capture_becomes_valid_only_after_replay(self):
        result = run_ui_scenario(
            """
  await nextTurn();
  const linux = term("slot0");
  linux.clientHeight = 100;
  linux.scrollHeight = 200;
  linux.scrollTop = 40;
  linux.dispatch("scroll");
  send({
    type: "exec", phase: "start", id: 42, target: "linux",
    cmd: "capture later", ts: "10:00:00.000",
  });
  send({
    type: "line", target: "linux", direction: "<<<",
    text: "delayed output", ts: "10:00:00.001",
  });
  send({
    type: "exec", phase: "end", id: 42, target: "linux",
    ended_by: "idle", ms: 10, bytes: 14, truncated: false, ok: true,
  });
  const execNode = document.getElementById("spine-body").children[0];
  execNode.dispatch("click");
  const before = {
    rows: linux.children.length,
    nodeClass: execNode.className,
  };
  linux.scrollTop = 100;
  linux.dispatch("scroll");
  const anchor = linux.children[0];
  execNode.dispatch("click");
  return {
    before,
    rows: linux.children.length,
    classes: linux.children.map((child) => child.className),
    anchorText: anchor.textContent,
    footText: linux.children[1].textContent,
    scrolled: !!anchor.scrolledIntoView,
    nodeClass: execNode.className,
  };
"""
        )

        self.assertEqual(0, result["before"]["rows"])
        self.assertIn("jump-miss", result["before"]["nodeClass"])
        self.assertEqual(2, result["rows"])
        self.assertEqual(
            ["ln", "dev", "capture-row", "cap-top", "cap-bot", "jump-flash"],
            result["classes"][0].split(" "),
        )
        self.assertEqual("cap-foot", result["classes"][1])
        self.assertIn("delayed output", result["anchorText"])
        self.assertIn("closed on idle", result["footText"])
        self.assertTrue(result["scrolled"])
        self.assertIn("jump-hit", result["nodeClass"])
        self.assertNotIn("jump-miss", result["nodeClass"])

    def test_detached_pre_capture_device_line_does_not_attach_to_later_capture(self):
        result = run_ui_scenario(
            """
  await nextTurn();
  const linux = term("slot0");
  linux.clientHeight = 100;
  linux.scrollHeight = 200;
  linux.scrollTop = 40;
  linux.dispatch("scroll");
  send({
    type: "line", target: "linux", direction: "<<<",
    text: "pre-capture-device", ts: "10:00:00.001",
  });
  send({
    type: "exec", phase: "start", id: 77, target: "linux",
    cmd: "later capture", ts: "10:00:00.002",
  });
  linux.scrollTop = 100;
  linux.dispatch("scroll");
  return {
    rows: linux.children.length,
    classes: linux.children.map((child) => child.className),
    texts: linux.children.map((child) => child.textContent),
    termText: linux.textContent,
  };
"""
        )

        self.assertEqual(1, result["rows"])
        self.assertEqual(["ln dev"], result["classes"])
        self.assertIn("pre-capture-device", result["texts"][0])
        self.assertIn("pre-capture-device", result["termText"])

    def test_recovery_moves_attached_capture_after_gap_preserving_order_and_trace_jump(self):
        result = run_ui_scenario(
            """
  await nextTurn();
  const linux = term("slot0");
  send({
    type: "exec", phase: "start", id: 55, target: "linux",
    cmd: "flood", ts: "10:00:00.000",
  });
  send({
    type: "line", target: "linux", direction: "<<<",
    text: "pre-detach-0", ts: "10:00:00.001",
  });
  linux.clientHeight = 100;
  linux.scrollHeight = 200;
  linux.scrollTop = 40;
  linux.dispatch("scroll");
  for (let index = 0; index < 40; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `flood-${index}` });
  }
  send({
    type: "exec", phase: "end", id: 55, target: "linux",
    ended_by: "idle", ms: 5, bytes: 40, truncated: false, ok: true,
  });
  send({ type: "line", target: "linux", direction: "---", text: "after-capture-system" });
  linux.scrollTop = 100;
  linux.dispatch("scroll");
  const execNode = document.getElementById("spine-body").children[0];
  execNode.dispatch("click");
  const rows = linux.children;
  const anchor = rows[1];
  return {
    rows: rows.length,
    classes: rows.map((child) => child.className),
    gapText: rows[0].textContent,
    captureTexts: rows.slice(1, 34).map((child) => child.textContent),
    footText: rows[34].textContent,
    lastRowText: rows[35].textContent,
    scrolled: !!anchor.scrolledIntoView,
    pill: document.getElementById("status-pill").textContent,
  };
"""
        )

        self.assertEqual(36, result["rows"])
        self.assertEqual("ln gap", result["classes"][0])
        self.assertEqual(
            ["ln", "dev", "capture-row", "cap-top", "jump-flash"],
            result["classes"][1].split(" "),
        )
        self.assertEqual("ln dev capture-row cap-mid", result["classes"][2])
        self.assertEqual("ln dev capture-row cap-bot", result["classes"][33])
        self.assertEqual("cap-foot", result["classes"][34])
        self.assertEqual("ln sys", result["classes"][35])
        self.assertEqual(
            "— 8 lines in session log, not in this view —",
            result["gapText"],
        )
        self.assertNotIn("flood-0", result["captureTexts"])
        self.assertNotIn("flood-7", result["captureTexts"])
        self.assertIn("pre-detach-0", result["captureTexts"][0])
        self.assertIn("flood-8", result["captureTexts"][1])
        self.assertIn("flood-39", result["captureTexts"][-1])
        self.assertIn("closed on idle", result["footText"])
        self.assertIn("after-capture-system", result["lastRowText"])
        self.assertTrue(result["scrolled"])
        self.assertNotEqual("not in view", result["pill"])

    def test_recovery_reattaches_a_budget_trimmed_capture_and_keeps_the_budget(self):
        result = run_ui_scenario(
            """
  document.getElementById("live-depth-500").dispatch("click");
  const linux = term("slot0");
  send({
    type: "exec", phase: "start", id: 9, target: "linux",
    cmd: "one-liner", ts: "10:00:00.000",
  });
  send({
    type: "line", target: "linux", direction: "<<<",
    text: "capture-line-0", ts: "10:00:00.001",
  });
  for (let index = 0; index < 499; index += 1) {
    send({ type: "line", target: "linux", direction: "---", text: `filler-${index}` });
  }
  linux.clientHeight = 100;
  linux.scrollHeight = 200;
  linux.scrollTop = 40;
  linux.dispatch("scroll");
  send({ type: "line", target: "linux", direction: "<<<", text: "buffered-into-capture" });
  send({
    type: "exec", phase: "end", id: 9, target: "linux",
    ended_by: "idle", ms: 5, bytes: 14, truncated: false, ok: true,
  });
  for (let index = 0; index < 201; index += 1) {
    send({ type: "line", target: "linux", direction: ">>>", who: "user", text: `write-${index}` });
  }
  linux.scrollTop = 100;
  linux.dispatch("scroll");
  const rows = linux.children;
  const captureAt = rows.findIndex((child) => child.classList.contains("capture-row"));
  return {
    rows: rows.length,
    counted: rows.filter((child) => child.classList.contains("ln")).length,
    retained: paneModelSpies[0].countedSize(),
    captureAt,
    captureClass: captureAt < 0 ? "" : rows[captureAt].className,
    captureText: captureAt < 0 ? "" : rows[captureAt].textContent,
    footClass: captureAt < 0 ? "" : rows[captureAt + 1].className,
    text: linux.textContent,
  };
"""
        )

        self.assertEqual(241, result["rows"])
        self.assertEqual(240, result["counted"])
        self.assertEqual(500, result["retained"])
        self.assertEqual(39, result["captureAt"])
        self.assertEqual("ln dev capture-row cap-top cap-bot", result["captureClass"])
        self.assertEqual("cap-foot", result["footClass"])
        self.assertIn("buffered-into-capture", result["captureText"])
        self.assertNotIn("capture-line-0", result["text"])
        self.assertNotIn("filler-0", result["text"])
        self.assertIn("filler-498", result["text"])
        self.assertIn("write-200", result["text"])

    def test_transcript_gap_counts_only_evicted_rows_against_budget(self):
        result = run_ui_scenario(
            """
  document.getElementById("live-depth-500").dispatch("click");
  const linux = term("slot0");
  for (let index = 0; index < 490; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `visible-${index}` });
  }
  flushFrames();
  linux.clientHeight = 100;
  linux.scrollHeight = 200;
  linux.scrollTop = 40;
  linux.dispatch("scroll");
  for (let index = 0; index < 40; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `omitted-${index}` });
  }
  linux.scrollTop = 100;
  linux.dispatch("scroll");
  return {
    rows: linux.children.length,
    classes: linux.children.map((child) => child.className),
    texts: linux.children.map((child) => child.textContent),
  };
"""
        )

        self.assertEqual(240, result["rows"])
        self.assertNotIn("visible-0", result["texts"])
        self.assertNotIn("visible-282", result["texts"])
        self.assertIn("visible-283", result["texts"][0])
        self.assertEqual("ln gap", result["classes"][207])
        self.assertEqual(
            "— 8 lines in session log, not in this view —",
            result["texts"][207],
        )
        self.assertNotIn("omitted-0", result["texts"])
        self.assertNotIn("omitted-7", result["texts"])
        self.assertIn("omitted-8", result["texts"][208])
        self.assertIn("omitted-39", result["texts"][239])

    def test_consecutive_detach_cycles_produce_separate_uncounted_gaps(self):
        result = run_ui_scenario(
            """
  const linux = term("slot0");
  linux.clientHeight = 100;
  linux.scrollHeight = 200;
  linux.scrollTop = 40;
  linux.dispatch("scroll");
  for (let index = 0; index < 40; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `cycle1-${index}` });
  }
  linux.scrollTop = 100;
  linux.dispatch("scroll");
  flushFrames();
  linux.scrollTop = 40;
  linux.dispatch("scroll");
  for (let index = 0; index < 40; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `cycle2-${index}` });
  }
  linux.scrollTop = 100;
  linux.dispatch("scroll");
  return {
    rows: linux.children.length,
    classes: linux.children.map((child) => child.className),
    texts: linux.children.map((child) => child.textContent),
  };
"""
        )

        self.assertEqual(66, result["rows"])
        self.assertEqual("ln gap", result["classes"][0])
        self.assertEqual(
            "— 8 lines in session log, not in this view —",
            result["texts"][0],
        )
        self.assertIn("cycle1-8", result["texts"][1])
        self.assertIn("cycle1-39", result["texts"][32])
        self.assertEqual("ln gap", result["classes"][33])
        self.assertEqual(
            "— 8 lines in session log, not in this view —",
            result["texts"][33],
        )
        self.assertIn("cycle2-8", result["texts"][34])
        self.assertIn("cycle2-39", result["texts"][65])
        self.assertNotIn("cycle1-0", result["texts"])
        self.assertNotIn("cycle2-0", result["texts"])

    def test_term_budget_counts_and_trims_captured_rows(self):
        result = run_ui_scenario(
            """
  send({ type: "exec", phase: "start", id: 51, target: "linux", cmd: "stream" });
  for (let index = 0; index < 75010; index += 1) {
    send({
      type: "line", target: "linux", direction: "<<<",
      text: `line-${index}`,
    });
  }
  const rows = term("slot0").children;
  return {
    termChildren: rows.length,
    captureRows: rows.filter((row) => row.classList.contains("capture-row")).length,
    retained: paneModelSpies[0].countedSize(),
    text: term("slot0").textContent,
  };
"""
        )

        self.assertEqual(240, result["termChildren"])
        self.assertEqual(240, result["captureRows"])
        self.assertEqual(75000, result["retained"])
        self.assertNotIn("line-0", result["text"])
        self.assertIn("line-75009", result["text"])

    def test_batched_line_items_append_in_order(self):
        result = run_ui_scenario(
            """
  send({
    type: "line",
    items: [
      { target: "linux", direction: "<<<", text: "first", ts: "1" },
      { target: "linux", direction: "<<<", text: "second", ts: "2" },
    ],
  });
  flushFrames();
  return {
    rows: term("slot0").children.length,
    text: term("slot0").textContent,
  };
"""
        )

        self.assertEqual(2, result["rows"])
        self.assertIn("first", result["text"])
        self.assertIn("second", result["text"])

    def test_flooding_target_forces_one_layout_read_per_frame(self):
        result = run_ui_scenario(
            """
  await nextTurn();
  const before = layoutReads;
  const beforeRows = rowLayoutReads;
  for (let index = 0; index < 500; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `line-${index}` });
  }
  const duringBurst = layoutReads - before;
  const rowsDuringBurst = rowLayoutReads - beforeRows;
  flushFrames();
  return {
    duringBurst,
    rowsDuringBurst,
    afterFlush: layoutReads - before,
    rowsAfterFlush: rowLayoutReads - beforeRows,
    rows: term("slot0").children.length,
    scrollTop: term("slot0").scrollTop,
  };
"""
        )

        self.assertEqual(240, result["rows"])
        self.assertEqual(0, result["duringBurst"])
        self.assertEqual(1, result["afterFlush"])
        self.assertEqual(240, result["scrollTop"])
        # Row overflow probing is deferred to the frame too, and only the rows that
        # survived trimming are measured, so a burst costs the window, not the burst.
        self.assertEqual(0, result["rowsDuringBurst"])
        self.assertEqual(240, result["rowsAfterFlush"])

    def test_stale_automatic_scroll_event_does_not_falsely_detach_a_following_pane(self):
        result = run_ui_scenario(
            """
  const linux = term("slot0");
  linux.clientHeight = 50;
  for (let index = 0; index < 60; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `seed-${index}` });
  }
  flushFrames();
  for (let index = 0; index < 40; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `flood-${index}` });
  }
  linux.dispatch("scroll");
  send({ type: "line", target: "linux", direction: "<<<", text: "after-stale-scroll" });
  flushFrames();
  return {
    rows: linux.children.length,
    text: linux.textContent,
    classes: linux.children.map((child) => child.className),
  };
"""
        )

        self.assertEqual(101, result["rows"])
        self.assertIn("after-stale-scroll", result["text"])
        self.assertNotIn("ln gap", result["classes"])

    def test_user_scroll_below_pending_auto_scroll_target_still_detaches(self):
        result = run_ui_scenario(
            """
  const linux = term("slot0");
  linux.clientHeight = 50;
  for (let index = 0; index < 90; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `seed-${index}` });
  }
  flushFrames();
  for (let index = 0; index < 10; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `flood-${index}` });
  }
  linux.scrollTop = 10;
  linux.dispatch("scroll");
  send({ type: "line", target: "linux", direction: "<<<", text: "after-user-scroll" });
  const rowsAfterDetach = linux.children.length;
  // A pane that has just detached may still be sitting in pendingScrolls from
  // auto-scrolls scheduled before the detach. The queued rAF flush must not
  // silently drag it back to the tail and let the resulting scroll event
  // reattach it, defeating the detach.
  flushFrames();
  linux.dispatch("scroll");
  send({ type: "line", target: "linux", direction: "<<<", text: "after-flush-scroll" });
  return {
    rowsAfterDetach,
    rows: linux.children.length,
    text: linux.textContent,
    scrollTop: linux.scrollTop,
  };
"""
        )

        self.assertEqual(100, result["rowsAfterDetach"])
        self.assertNotIn("after-user-scroll", result["text"])
        self.assertEqual(100, result["rows"])
        self.assertNotIn("after-flush-scroll", result["text"])
        self.assertEqual(10, result["scrollTop"])

    def test_trimming_past_the_budget_does_not_rescan_the_scrollback(self):
        result = run_ui_scenario(
            """
  for (let index = 0; index < 75000; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `fill-${index}` });
  }
  flushFrames();
  const before = childrenReads;
  for (let index = 0; index < 200; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `trim-${index}` });
  }
  flushFrames();
  return {
    scans: childrenReads - before,
    rows: term("slot0").children.length,
    retained: paneModelSpies[0].countedSize(),
  };
"""
        )

        self.assertEqual(240, result["rows"])
        self.assertEqual(75000, result["retained"])
        self.assertEqual(0, result["scans"])

    def test_spine_client_buffer_is_capped_at_server_ring_size(self):
        result = run_ui_scenario(
            """
  await nextTurn();
  for (let index = 0; index < 60; index += 1) {
    send({
      type: "line", target: "rtos", direction: ">>>", who: "agent",
      text: `send-${index}`, ts: "10:20:31.000",
    });
  }
  const body = document.getElementById("spine-body");
  return {
    count: body.children.length,
    text: body.textContent,
    tally: document.getElementById("spine-tally").textContent,
  };
"""
        )

        self.assertEqual(50, result["count"])
        self.assertNotIn("send-0", result["text"])
        self.assertIn("send-59", result["text"])
        self.assertIn("send 50", result["tally"])

    def test_status_busy_and_unmatched_end_do_not_invent_capture(self):
        result = run_ui_scenario(
            """
  send({
    type: "status", mode: "bridge",
    ports: {
      linux: {
        name: "linux", title: "Linux", com: "COM3", baud: 115200,
        open: true, busy: true,
      },
      rtos: {
        name: "rtos", title: "RTOS", com: "COM6", baud: 115200,
        open: true, busy: true,
      },
    },
  });
  send({
    type: "exec", phase: "end", id: 99, target: "linux",
    ended_by: "idle", ms: 1, bytes: 0, truncated: false, ok: true,
  });
  return {
    holderText: holder("slot0").textContent,
    holderClass: holder("slot0").className,
    termChildren: term("slot0").children.length,
  };
"""
        )

        self.assertEqual("IDLE", result["holderText"])
        self.assertEqual("holder idle", result["holderClass"])
        self.assertEqual(0, result["termChildren"])

    def test_stale_exec_end_does_not_extinguish_newer_running_holder(self):
        result = run_ui_scenario(
            """
  await nextTurn();
  send({ type: "exec", phase: "start", id: 100, target: "linux", cmd: "new" });
  send({
    type: "exec", phase: "end", id: 99, target: "linux",
    ended_by: "idle", ms: 1, bytes: 0, truncated: false, ok: true,
  });
  return {
    holderText: holder("slot0").textContent,
    holderClass: holder("slot0").className,
  };
"""
        )

        self.assertEqual("AGENT EXEC", result["holderText"])
        self.assertEqual("holder agent", result["holderClass"])

    def test_clear_mid_exec_discards_capture_and_resets_holder(self):
        result = run_ui_scenario(
            """
  send({ type: "exec", phase: "start", id: 21, target: "linux" });
  send({ type: "line", target: "linux", direction: "<<<", text: "before clear" });
  document.getElementById("btn-clear").dispatch("click");
  const afterClear = {
    holderText: holder("slot0").textContent,
    holderClass: holder("slot0").className,
    termChildren: term("slot0").children.length,
  };
  send({ type: "line", target: "linux", direction: "<<<", text: "after clear" });
  send({
    type: "exec", phase: "end", id: 21, target: "linux",
    ended_by: "idle", ms: 20, bytes: 11, truncated: false, ok: true,
  });
  return {
    afterClear,
    termClasses: term("slot0").children.map((child) => child.className),
    termText: term("slot0").textContent,
    holderText: holder("slot0").textContent,
  };
"""
        )

        self.assertEqual(
            {
                "holderText": "IDLE",
                "holderClass": "holder idle",
                "termChildren": 0,
            },
            result["afterClear"],
        )
        self.assertEqual(["ln dev"], result["termClasses"])
        self.assertIn("after clear", result["termText"])
        self.assertEqual("IDLE", result["holderText"])

    def test_trace_jump_scrolls_to_capture_and_highlights(self):
        result = run_ui_scenario(
            """
  await nextTurn();
  send({
    type: "exec", phase: "start", id: 8, target: "rtos",
    cmd: "svc_rec fstop 0x3f", ts: "10:00:00.000",
  });
  send({
    type: "line", target: "rtos", direction: ">>>", who: "agent",
    text: "svc_rec fstop 0x3f", ts: "10:00:00.001",
  });
  send({
    type: "line", target: "rtos", direction: "<<<",
    text: "ok", ts: "10:00:00.002",
  });
  send({
    type: "exec", phase: "end", id: 8, target: "rtos",
    ended_by: "idle", ms: 2090, bytes: 6656, truncated: false, ok: true,
  });
  const body = document.getElementById("spine-body");
  const execNode = body.children[0];
  const capture = term("slot1").children[1];
  const pillBefore = document.getElementById("status-pill").textContent;
  execNode.dispatch("click");
  return {
    title: execNode.title,
    className: execNode.className,
    scrolled: !!capture.scrolledIntoView,
    scrollOptions: capture.scrollIntoViewOptions,
    captureClass: capture.className,
    pillBefore,
    pill: document.getElementById("status-pill").textContent,
  };
"""
        )

        self.assertEqual("Jump to capture", result["title"])
        self.assertIn("exec", result["className"])
        self.assertTrue(result["scrolled"])
        self.assertIn("jump-flash", result["captureClass"])
        self.assertIn("jump-hit", result["className"])
        self.assertEqual(result["pillBefore"], result["pill"])

    def test_trace_jump_positions_the_capture_without_a_smooth_animation(self):
        # A smooth animation outlasts the capture highlight over long distances, so the
        # Operator arrives after the highlight is already gone.
        result = run_ui_scenario(
            """
  await nextTurn();
  send({
    type: "exec", phase: "start", id: 4, target: "linux",
    cmd: "dmesg", ts: "10:00:00.000",
  });
  send({
    type: "line", target: "linux", direction: "<<<", text: "boot ok",
  });
  send({
    type: "exec", phase: "end", id: 4, target: "linux",
    ended_by: "idle", ms: 10, bytes: 7, truncated: false, ok: true,
  });
  const capture = term("slot0").children[0];
  document.getElementById("spine-body").children[0].dispatch("click");
  return { scrollOptions: capture.scrollIntoViewOptions };
"""
        )

        self.assertEqual("nearest", result["scrollOptions"]["block"])
        self.assertNotEqual("smooth", result["scrollOptions"].get("behavior"))

    def test_trace_jump_without_a_capture_marks_the_clicked_node_not_the_pill(self):
        result = run_ui_scenario(
            """
  await nextTurn();
  send({
    type: "exec", phase: "start", id: 21, target: "linux",
    cmd: "before clear", ts: "10:00:00.000",
  });
  send({
    type: "line", target: "linux", direction: "<<<", text: "visible",
  });
  send({
    type: "exec", phase: "end", id: 21, target: "linux",
    ended_by: "idle", ms: 10, bytes: 7, truncated: false, ok: true,
  });
  document.getElementById("btn-clear").dispatch("click");
  const pillBefore = document.getElementById("status-pill").textContent;
  const execNode = document.getElementById("spine-body").children[0];
  execNode.dispatch("click");
  return {
    nodeClass: execNode.className,
    pillBefore,
    pill: document.getElementById("status-pill").textContent,
  };
"""
        )

        self.assertIn("jump-miss", result["nodeClass"])
        self.assertEqual(result["pillBefore"], result["pill"])

    def test_trace_jump_miss_marker_stays_on_the_most_recently_clicked_node(self):
        result = run_ui_scenario(
            """
  await nextTurn();
  send({
    type: "exec", phase: "start", id: 1, target: "linux",
    cmd: "first", ts: "10:00:00.000",
  });
  send({
    type: "exec", phase: "start", id: 2, target: "linux",
    cmd: "second", ts: "10:00:01.000",
  });
  const body = document.getElementById("spine-body");
  body.children[0].dispatch("click");
  body.children[1].dispatch("click");
  return { classes: body.children.map((child) => child.className) };
"""
        )

        self.assertNotIn("jump-miss", result["classes"][0])
        self.assertIn("jump-miss", result["classes"][1])

    def test_trace_jump_running_without_output_marks_the_clicked_node(self):
        result = run_ui_scenario(
            """
  await nextTurn();
  send({
    type: "exec", phase: "start", id: 3, target: "linux",
    cmd: "pending", ts: "10:00:00.000",
  });
  const pillBefore = document.getElementById("status-pill").textContent;
  const execNode = document.getElementById("spine-body").children[0];
  execNode.dispatch("click");
  return {
    termChildren: term("slot0").children.length,
    nodeClass: execNode.className,
    pillBefore,
    pill: document.getElementById("status-pill").textContent,
  };
"""
        )

        self.assertEqual(0, result["termChildren"])
        self.assertIn("jump-miss", result["nodeClass"])
        self.assertEqual(result["pillBefore"], result["pill"])

    def test_send_spine_node_is_not_jumpable(self):
        result = run_ui_scenario(
            """
  await nextTurn();
  send({
    type: "line", target: "linux", direction: ">>>", who: "agent",
    text: "reboot", ts: "10:00:00.000",
  });
  const sendNode = document.getElementById("spine-body").children[0];
  sendNode.dispatch("click");
  return {
    title: sendNode.title || "",
    className: sendNode.className,
    pill: document.getElementById("status-pill").textContent,
  };
"""
        )

        self.assertEqual("", result["title"])
        self.assertEqual("spine-node send", result["className"])
        self.assertNotEqual("not in view", result["pill"])


class FollowedWindowTest(unittest.TestCase):
    def test_followed_window_materializes_240_while_the_model_retains_the_budget(self):
        result = run_ui_scenario(
            """
  document.getElementById("live-depth-500").dispatch("click");
  for (let index = 0; index < 620; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `line-${index}` });
  }
  flushFrames();
  const rows = term("slot0").children;
  return {
    domRows: rows.length,
    modelCounted: paneModelSpies[0].countedSize(),
    classes: [...new Set(rows.map((child) => child.className))],
    firstText: rows[0].textContent,
    lastText: rows[rows.length - 1].textContent,
    text: term("slot0").textContent,
  };
"""
        )

        self.assertEqual(240, result["domRows"])
        self.assertEqual(500, result["modelCounted"])
        self.assertEqual(["ln dev"], result["classes"])
        self.assertIn("line-380", result["firstText"])
        self.assertIn("line-619", result["lastText"])
        self.assertNotIn("line-379", result["text"])

    def test_each_pane_enforces_its_own_240_entry_window(self):
        result = run_ui_scenario(
            """
  for (let index = 0; index < 300; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `linux-${index}` });
  }
  const afterLinuxFlood = term("slot1").children.length;
  for (let index = 0; index < 300; index += 1) {
    send({ type: "line", target: "rtos", direction: "<<<", text: `rtos-${index}` });
  }
  flushFrames();
  return {
    afterLinuxFlood,
    rows0: term("slot0").children.length,
    rows1: term("slot1").children.length,
    first0: term("slot0").children[0].textContent,
    first1: term("slot1").children[0].textContent,
  };
"""
        )

        self.assertEqual(0, result["afterLinuxFlood"])
        self.assertEqual(240, result["rows0"])
        self.assertEqual(240, result["rows1"])
        self.assertIn("linux-60", result["first0"])
        self.assertIn("rtos-60", result["first1"])

    def test_transcript_gap_occupies_exactly_one_followed_window_entry(self):
        result = run_ui_scenario(
            """
  const linux = term("slot0");
  for (let index = 0; index < 240; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `visible-${index}` });
  }
  flushFrames();
  linux.clientHeight = 100;
  linux.scrollHeight = 200;
  linux.scrollTop = 40;
  linux.dispatch("scroll");
  for (let index = 0; index < 40; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `omitted-${index}` });
  }
  linux.scrollTop = 100;
  linux.dispatch("scroll");
  const rows = linux.children;
  return {
    rows: rows.length,
    gaps: rows.filter((child) => child.className === "ln gap").length,
    gapIndex: rows.findIndex((child) => child.className === "ln gap"),
    gapText: rows[207].textContent,
    beforeGap: rows[206].textContent,
    afterGap: rows[208].textContent,
    lastText: rows[239].textContent,
  };
"""
        )

        self.assertEqual(240, result["rows"])
        self.assertEqual(1, result["gaps"])
        self.assertEqual(207, result["gapIndex"])
        self.assertEqual(
            "— 8 lines in session log, not in this view —",
            result["gapText"],
        )
        self.assertIn("visible-239", result["beforeGap"])
        self.assertIn("omitted-8", result["afterGap"])
        self.assertIn("omitted-39", result["lastText"])

    def test_tightening_the_budget_retrims_the_window_without_a_gap(self):
        # Every selectable budget (500 / 5000 / 75000) is above the 240-entry window, so
        # tightening can only shrink retention; the window limit is min(240, budget).
        result = run_ui_scenario(
            """
  for (let index = 0; index < 620; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `line-${index}` });
  }
  flushFrames();
  const before = {
    domRows: term("slot0").children.length,
    modelCounted: paneModelSpies[0].countedSize(),
  };
  document.getElementById("live-depth-500").dispatch("click");
  const rows = term("slot0").children;
  return {
    before,
    domRows: rows.length,
    modelCounted: paneModelSpies[0].countedSize(),
    gaps: rows.filter((child) => child.className === "ln gap").length,
    firstText: rows[0].textContent,
  };
"""
        )

        self.assertEqual(240, result["before"]["domRows"])
        self.assertEqual(620, result["before"]["modelCounted"])
        self.assertEqual(240, result["domRows"])
        self.assertEqual(500, result["modelCounted"])
        self.assertEqual(0, result["gaps"])
        self.assertIn("line-380", result["firstText"])

    def test_capture_row_chrome_survives_trimming_the_oldest_captured_rows(self):
        result = run_ui_scenario(
            """
  send({ type: "exec", phase: "start", id: 5, target: "linux", cmd: "stream" });
  for (let index = 0; index < 300; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `cap-${index}` });
  }
  flushFrames();
  const running = {
    rows: term("slot0").children.length,
    tops: term("slot0").children.filter((r) => r.classList.contains("cap-top")).length,
    bots: term("slot0").children.filter((r) => r.classList.contains("cap-bot")).length,
  };
  send({
    type: "exec", phase: "end", id: 5, target: "linux",
    ended_by: "idle", ms: 30, bytes: 300, truncated: false, ok: true,
  });
  const rows = term("slot0").children;
  return {
    running,
    rows: rows.length,
    tops: rows.filter((r) => r.classList.contains("cap-top")).length,
    bots: rows.filter((r) => r.classList.contains("cap-bot")).length,
    firstClass: rows[0].className,
    firstText: rows[0].textContent,
    midClass: rows[1].className,
    lastRowClass: rows[rows.length - 2].className,
    footClass: rows[rows.length - 1].className,
    execIds: [...new Set(rows.map((r) => r.dataset.execId))],
    footText: rows[rows.length - 1].textContent,
  };
"""
        )

        self.assertEqual(240, result["running"]["rows"])
        self.assertEqual(1, result["running"]["tops"])
        self.assertEqual(0, result["running"]["bots"])
        self.assertEqual(241, result["rows"])
        self.assertEqual(1, result["tops"])
        self.assertEqual(1, result["bots"])
        self.assertEqual("ln dev capture-row cap-top", result["firstClass"])
        self.assertIn("cap-60", result["firstText"])
        self.assertEqual("ln dev capture-row cap-mid", result["midClass"])
        self.assertEqual("ln dev capture-row cap-bot", result["lastRowClass"])
        self.assertEqual("cap-foot", result["footClass"])
        self.assertEqual(["5"], result["execIds"])
        self.assertIn("closed on idle", result["footText"])

    def test_trace_jump_lands_on_the_promoted_anchor_of_a_windowed_capture(self):
        result = run_ui_scenario(
            """
  await nextTurn();
  send({ type: "exec", phase: "start", id: 7, target: "linux", cmd: "dmesg" });
  for (let index = 0; index < 50; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `cap-${index}` });
  }
  send({
    type: "exec", phase: "end", id: 7, target: "linux",
    ended_by: "idle", ms: 12, bytes: 50, truncated: false, ok: true,
  });
  for (let index = 0; index < 200; index += 1) {
    send({ type: "line", target: "linux", direction: "---", text: `filler-${index}` });
  }
  flushFrames();
  const execNode = document.getElementById("spine-body").children[0];
  execNode.dispatch("click");
  const anchor = term("slot0").children[0];
  return {
    rows: term("slot0").children.length,
    anchorClass: anchor.className,
    anchorText: anchor.textContent,
    scrolled: !!anchor.scrolledIntoView,
    nodeClass: execNode.className,
  };
"""
        )

        self.assertEqual(241, result["rows"])
        self.assertIn("cap-top", result["anchorClass"].split(" "))
        self.assertIn("jump-flash", result["anchorClass"].split(" "))
        self.assertIn("cap-10", result["anchorText"])
        self.assertTrue(result["scrolled"])
        self.assertIn("jump-hit", result["nodeClass"])

    def test_programmatic_tail_scrolling_under_a_flood_keeps_follow_attached(self):
        result = run_ui_scenario(
            """
  const linux = term("slot0");
  linux.clientHeight = 50;
  for (let batch = 0; batch < 30; batch += 1) {
    for (let index = 0; index < 10; index += 1) {
      send({ type: "line", target: "linux", direction: "<<<", text: `flood-${batch}-${index}` });
    }
    flushFrames();
    linux.dispatch("scroll");
  }
  send({ type: "line", target: "linux", direction: "<<<", text: "after-flood" });
  flushFrames();
  const rows = linux.children;
  return {
    rows: rows.length,
    gaps: rows.filter((child) => child.className === "ln gap").length,
    lastText: rows[rows.length - 1].textContent,
    scrollTop: linux.scrollTop,
  };
"""
        )

        self.assertEqual(240, result["rows"])
        self.assertEqual(0, result["gaps"])
        self.assertIn("after-flood", result["lastText"])
        self.assertEqual(190, result["scrollTop"])

    def test_followed_panes_opt_out_of_browser_scroll_anchoring(self):
        # Trimming removes rows above the viewport on every frame, and scroll anchoring
        # answers by pulling scrollTop back by the removed height, which the pane reads as
        # a scroll away from the live tail and detaches Follow. The fake DOM cannot model
        # anchoring, so this guards the declaration the headed gate depends on.
        css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
        block = css[css.index(".screen {") :]
        self.assertIn("overflow-anchor: none", block[: block.index("}")])

    def test_overflowed_rows_get_a_keyboard_expand_toggle_and_plain_rows_do_not(self):
        result = run_ui_scenario(
            """
  send({ type: "line", target: "linux", direction: "<<<", text: "short" });
  send({ type: "line", target: "linux", direction: "<<<", text: "a very long device line" });
  const rows = term("slot0").children;
  const longBody = rows[1].children[1];
  longBody.scrollHeight = 72;
  longBody.clientHeight = 24;
  flushFrames();
  const plainChildren = rows[0].children.length;
  const toggle = rows[1].children[2];
  const clamped = { rowClass: rows[1].className, aria: toggle.attributes["aria-expanded"] };
  term("slot0").dispatch("click", { target: toggle });
  const expanded = { rowClass: rows[1].className, aria: toggle.attributes["aria-expanded"] };
  term("slot0").dispatch("click", { target: toggle });
  return {
    plainChildren,
    plainClass: rows[0].className,
    longChildren: rows[1].children.length,
    clamped,
    expanded,
    collapsed: { rowClass: rows[1].className, aria: toggle.attributes["aria-expanded"] },
    tag: toggle.tagName,
    type: toggle.attributes["type"],
    label: toggle.attributes["aria-label"],
  };
"""
        )

        self.assertEqual(2, result["plainChildren"])
        self.assertEqual("ln dev", result["plainClass"])
        self.assertEqual(3, result["longChildren"])
        self.assertIn("clamped", result["clamped"]["rowClass"].split(" "))
        self.assertEqual("false", result["clamped"]["aria"])
        self.assertIn("expanded", result["expanded"]["rowClass"].split(" "))
        self.assertEqual("true", result["expanded"]["aria"])
        self.assertNotIn("expanded", result["collapsed"]["rowClass"].split(" "))
        self.assertEqual("false", result["collapsed"]["aria"])
        self.assertEqual("BUTTON", result["tag"])
        self.assertEqual("button", result["type"])
        self.assertTrue(result["label"])


if __name__ == "__main__":
    unittest.main()
