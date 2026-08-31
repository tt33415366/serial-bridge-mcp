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
globalThis.measureRowHeight = null;
globalThis.measureElementRect = null;
globalThis.onCreateElement = null;

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
    this.style = {{}};
    this._offsetHeight = null;
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
  // A materialized row's rendered height. A scenario either pins it per element or
  // supplies globalThis.measureRowHeight; unmeasured rows report 0, which the app treats
  // as "not measurable" and leaves on its estimate.
  get offsetHeight() {{
    if (this._offsetHeight !== null) return this._offsetHeight;
    return globalThis.measureRowHeight ? globalThis.measureRowHeight(this) : 0;
  }}
  set offsetHeight(value) {{
    this._offsetHeight = Number(value);
  }}
  // The app measures rows sub-pixel; the fake layout has only whole-pixel heights, so the
  // rect simply reports the same height a real browser would round into offsetHeight.
  getBoundingClientRect() {{
    if (globalThis.measureElementRect) return globalThis.measureElementRect(this);
    const height = this.offsetHeight;
    return {{ top: 0, left: 0, right: 0, bottom: height, width: 0, height }};
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
    if (globalThis.onCreateElement) globalThis.onCreateElement(element);
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
// Reading the whole retained list is the thing detached scrolling must never do, so the
// spy counts both the full-copy and the windowed read, plus the retained-depth capture
// scan that only a Trace Jump click is allowed to pay for.
globalThis.paneReads = {{ entries: 0, slice: 0, captureRange: 0 }};
globalThis.TranscriptView.createPane = (budget) => {{
  const pane = createRealPane(budget);
  const spy = {{ ...pane }};
  spy.entries = (...args) => {{
    paneReads.entries += 1;
    return pane.entries(...args);
  }};
  spy.slice = (...args) => {{
    paneReads.slice += 1;
    return pane.slice(...args);
  }};
  spy.captureRange = (...args) => {{
    paneReads.captureRange += 1;
    return pane.captureRange(...args);
  }};
  paneModelSpies.push(spy);
  return spy;
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

    def test_reattach_schedules_tail_scroll_after_gap_recovery(self):
        result = run_ui_scenario(
            """
  const linux = term("slot0");
  linux.clientHeight = 100;
  linux.scrollHeight = 200;
  linux.scrollTop = 40;
  linux.dispatch("scroll");
  send({
    type: "line", target: "linux", direction: "<<<",
    text: "omitted-while-detached",
  });
  const textBefore = linux.textContent;
  const detachedTop = linux.scrollTop;
  linux.scrollTop = linux.scrollHeight;
  linux.dispatch("scroll");
  flushFrames();
  return {
    textBefore,
    detachedTop,
    afterTop: linux.scrollTop,
    text: linux.textContent,
    followingNearTail: (linux.scrollHeight - linux.clientHeight - linux.scrollTop) <= 32,
  };
"""
        )
        self.assertNotIn("omitted-while-detached", result["textBefore"])
        self.assertIn("omitted-while-detached", result["text"])
        self.assertTrue(result["followingNearTail"])
        self.assertGreaterEqual(result["afterTop"], result["detachedTop"])

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

    def test_trace_jump_lands_on_the_first_retained_line_of_a_windowed_capture(self):
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
  const promoted = term("slot0").children[0];
  const head = { className: promoted.className, text: promoted.textContent };
  const execNode = document.getElementById("spine-body").children[0];
  execNode.dispatch("click");
  const rows = term("slot0").children;
  const anchor = rows[1];
  return {
    head,
    rows: rows.length,
    spacers: rows.filter((c) => c.className === "transcript-spacer").length,
    anchorClass: anchor.className,
    anchorText: anchor.textContent,
    scrolled: !!anchor.scrolledIntoView,
    nodeClass: execNode.className,
  };
"""
        )

        # The window trimmed cap-0 through cap-9 away and handed the capture's chrome to
        # cap-10, which is the fragment head a DOM-only jump would settle for.
        self.assertIn("cap-top", result["head"]["className"].split(" "))
        self.assertIn("cap-10", result["head"]["text"])

        # Retention still holds cap-0, so that is where the jump has to land.
        self.assertEqual(242, result["rows"])
        self.assertEqual(2, result["spacers"])
        self.assertIn("cap-top", result["anchorClass"].split(" "))
        self.assertIn("jump-flash", result["anchorClass"].split(" "))
        self.assertIn("cap-0", result["anchorText"])
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


# 1000 retained lines, a 240-row followed window, then one genuine scroll away from the
# live tail. Every entry is estimated at 18px, so the virtual content is 18000px tall and
# every offset below is exact rather than approximate.
DETACH_1000 = """
  const linux = term("slot0");
  for (let index = 0; index < 1000; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `line-${index}` });
  }
  flushFrames();
  linux.clientHeight = 400;
  linux.scrollHeight = 18000;
  linux.scrollTop = 100;
  linux.dispatch("scroll");
  flushFrames();
"""

# 300 leading lines, a sealed 100-line capture (its footer is retained entry 400), then
# 700 trailing lines: 1101 retained entries, 19818px of virtual content.
DETACH_CAPTURE = """
  const linux = term("slot0");
  for (let index = 0; index < 300; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `pre-${index}` });
  }
  send({ type: "exec", phase: "start", id: 7, target: "linux", cmd: "dmesg" });
  for (let index = 0; index < 100; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `cap-${index}` });
  }
  send({
    type: "exec", phase: "end", id: 7, target: "linux",
    ended_by: "idle", ms: 12, bytes: 100, truncated: false, ok: true,
  });
  for (let index = 0; index < 700; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `post-${index}` });
  }
  flushFrames();
  linux.clientHeight = 400;
  linux.scrollHeight = 19818;
  linux.scrollTop = 100;
  linux.dispatch("scroll");
  flushFrames();
"""

# 800 leading lines and a capture that is still open when the pane detaches, so its last
# row is materialized and `openCaptures` still points at it. Sealing from here is what
# used to splice a footer into the historical DOM behind the window's back. 900 retained
# entries, one more once the footer lands, so 16218px of virtual content.
DETACH_OPEN_CAPTURE = """
  const linux = term("slot0");
  for (let index = 0; index < 800; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `pre-${index}` });
  }
  send({ type: "exec", phase: "start", id: 7, target: "linux", cmd: "dmesg" });
  for (let index = 0; index < 100; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `cap-${index}` });
  }
  flushFrames();
  linux.clientHeight = 400;
  linux.scrollHeight = 16218;
  linux.scrollTop = 500;
  linux.dispatch("scroll");
  flushFrames();
"""

# Materialized rows read against the retained entries they claim to be showing, so a
# misalignment names the row that drifted instead of failing as a bare count.
ALIGNED_WITH = """
  const alignedWith = (from, to) => {
    const rows = linux.children.filter((c) => c.className !== "transcript-spacer");
    const entries = paneModelSpies[0].slice(from, to);
    if (rows.length !== entries.length) {
      return `${rows.length} rows vs ${entries.length} entries`;
    }
    for (let i = 0; i < rows.length; i += 1) {
      if (!rows[i].textContent.includes(entries[i].text)) {
        return `row ${i} "${rows[i].textContent}" vs entry "${entries[i].text}"`;
      }
    }
    return "aligned";
  };
"""

# 800 leading lines and a 100-row capture still running when the pane detaches. The two
# re-windows matter: they hand the capture's rows from the live append path to the history
# renderer, which is the ownership boundary a capture spanning the detach has to survive.
# 900 retained entries, 901 once the seal lands, so 16218px of virtual content.
DETACH_SPANNING_CAPTURE = """
  const linux = term("slot0");
  for (let index = 0; index < 800; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `pre-${index}` });
  }
  send({ type: "exec", phase: "start", id: 7, target: "linux", cmd: "dmesg" });
  for (let index = 0; index < 100; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `cap-${index}` });
  }
  flushFrames();
  linux.clientHeight = 400;
  linux.scrollHeight = 16218;
  linux.scrollTop = 500;
  linux.dispatch("scroll");
  flushFrames();
"""

# One capture must read as one run: the chrome is counted across the whole pane, and the
# capture rows have to occupy one unbroken stretch of it.
CAPTURE_SHAPE = """
  const shape = () => {
    const rows = linux.children;
    const spread = rows
      .map((c, i) => (c.classList.contains("capture-row") ? i : -1))
      .filter((i) => i >= 0);
    return {
      capTops: rows.filter((c) => c.classList.contains("cap-top")).length,
      capBots: rows.filter((c) => c.classList.contains("cap-bot")).length,
      feet: rows.filter((c) => c.className === "cap-foot").length,
      gaps: rows.filter((c) => c.className === "ln gap").length,
      gapAt: rows.findIndex((c) => c.className === "ln gap"),
      topAt: rows.findIndex((c) => c.classList.contains("cap-top")),
      footAt: rows.findIndex((c) => c.className === "cap-foot"),
      capRows: spread.length,
      contiguous: spread.length > 0 && spread[spread.length - 1] - spread[0] === spread.length - 1,
      firstCapText: spread.length ? rows[spread[0]].textContent : "",
      lastCapText: spread.length ? rows[spread[spread.length - 1]].textContent : "",
    };
  };
  const jump = () => {
    const node = document.getElementById("spine-body").children[0];
    node.dispatch("click");
    const hit = linux.children.find((c) => c.classList.contains("jump-flash"));
    return {
      node: node.className,
      row: hit ? hit.textContent : null,
      rowClass: hit ? hit.className : null,
    };
  };
  const bufferAndSeal = (count) => {
    for (let index = 0; index < count; index += 1) {
      send({ type: "line", target: "linux", direction: "<<<", text: `buffered-${index}` });
    }
    send({
      type: "exec", phase: "end", id: 7, target: "linux",
      ended_by: "idle", ms: 12, bytes: 100, truncated: false, ok: true,
    });
    flushFrames();
  };
  const reattach = () => {
    linux.scrollTop = 15818;
    linux.dispatch("scroll");
    flushFrames();
  };
"""

# Unmeasured fake rows report 0px, which collapses the virtual extent and leaves the pane
# unable to notice it has scrolled off its own window — so no re-window ever happens.
# Reporting the same 18px the height index estimates makes the geometry coherent, and a
# scroll then re-windows for the reason it would in a browser.
MEASURED_ROWS = """
  globalThis.measureRowHeight = () => 18;
"""

SCROLL_TO = """
  const scrollTo = (top) => {
    linux.scrollTop = top;
    linux.dispatch("scroll");
    flushFrames();
  };
  const kids = () => linux.children;
  const chrome = () => {
    const rows = linux.children;
    return {
      children: rows.length,
      counted: rows.filter((c) => c.classList.contains("ln")).length,
      tops: rows.filter((c) => c.classList.contains("cap-top")).length,
      mids: rows.filter((c) => c.classList.contains("cap-mid")).length,
      bots: rows.filter((c) => c.classList.contains("cap-bot")).length,
      feet: rows.filter((c) => c.className === "cap-foot").length,
    };
  };
"""


class DetachedHistoryWindowTest(unittest.TestCase):
    def test_scrolling_away_renders_an_older_slice_between_two_spacers(self):
        result = run_ui_scenario(
            DETACH_1000
            + """
  const rows = linux.children;
  return {
    children: rows.length,
    counted: rows.filter((c) => c.classList.contains("ln")).length,
    spacers: rows.filter((c) => c.className === "transcript-spacer").length,
    topClass: rows[0].className,
    bottomClass: rows[rows.length - 1].className,
    topHeight: rows[0].style.height,
    bottomHeight: rows[rows.length - 1].style.height,
    firstText: rows[1].textContent,
    lastText: rows[rows.length - 2].textContent,
    retained: paneModelSpies[0].countedSize(),
  };
"""
        )

        self.assertEqual(242, result["children"])
        self.assertEqual(240, result["counted"])
        self.assertEqual(2, result["spacers"])
        self.assertEqual("transcript-spacer", result["topClass"])
        self.assertEqual("transcript-spacer", result["bottomClass"])
        # 645 unmaterialized entries above, 115 below, at the 18px estimate.
        self.assertEqual("11610px", result["topHeight"])
        self.assertEqual("2070px", result["bottomHeight"])
        self.assertIn("line-645", result["firstText"])
        self.assertIn("line-884", result["lastText"])
        self.assertEqual(1000, result["retained"])

    def test_repeated_window_shifts_expose_contiguous_ordered_lines(self):
        result = run_ui_scenario(
            DETACH_1000
            + SCROLL_TO
            + r"""
  const snapshot = () => {
    const nums = linux.children
      .filter((c) => c.classList.contains("ln"))
      .map((c) => Number(c.textContent.match(/line-(\d+)/)[1]));
    let contiguous = true;
    for (let i = 1; i < nums.length; i += 1) {
      if (nums[i] !== nums[i - 1] + 1) contiguous = false;
    }
    return {
      count: nums.length,
      unique: new Set(nums).size,
      first: nums[0],
      last: nums[nums.length - 1],
      contiguous,
      top: linux.children[0].style.height,
    };
  };
  const shots = [snapshot()];
  for (const top of [11700, 3600, 8100, 900, 15000]) {
    scrollTo(top);
    shots.push(snapshot());
  }
  return { shots };
"""
        )

        expected = [(645, 884), (530, 769), (80, 319), (330, 569), (0, 239), (713, 952)]
        for shot, (first, last) in zip(result["shots"], expected):
            with self.subTest(first=first):
                self.assertEqual(240, shot["count"])
                self.assertEqual(240, shot["unique"])
                self.assertTrue(shot["contiguous"])
                self.assertEqual(first, shot["first"])
                self.assertEqual(last, shot["last"])
        self.assertEqual("0px", result["shots"][4]["top"])

    def test_slice_holding_a_whole_capture_draws_one_box_and_one_footer(self):
        result = run_ui_scenario(
            DETACH_CAPTURE
            + SCROLL_TO
            + """
  scrollTo(6300);
  const rows = linux.children;
  return {
    ...chrome(),
    topRowClass: rows[71].className,
    topRowText: rows[71].textContent,
    botRowClass: rows[170].className,
    botRowText: rows[170].textContent,
    footClass: rows[171].className,
    footText: rows[171].textContent,
    beforeCapture: rows[70].textContent,
    afterFoot: rows[172].textContent,
    execIds: [...new Set(rows.filter((c) => c.classList.contains("capture-row")).map((c) => c.dataset.execId))],
  };
"""
        )

        self.assertEqual(242, result["children"])
        self.assertEqual(239, result["counted"])
        self.assertEqual(1, result["tops"])
        self.assertEqual(98, result["mids"])
        self.assertEqual(1, result["bots"])
        self.assertEqual(1, result["feet"])
        self.assertEqual("ln dev capture-row cap-top", result["topRowClass"])
        self.assertIn("cap-0", result["topRowText"])
        self.assertEqual("ln dev capture-row cap-bot", result["botRowClass"])
        self.assertIn("cap-99", result["botRowText"])
        self.assertEqual("cap-foot", result["footClass"])
        self.assertIn("closed on idle", result["footText"])
        self.assertIn("pre-299", result["beforeCapture"])
        self.assertIn("post-0", result["afterFoot"])
        self.assertEqual(["7"], result["execIds"])

    def test_slice_cut_by_a_capture_boundary_keeps_the_box_without_a_stray_footer(self):
        result = run_ui_scenario(
            DETACH_CAPTURE
            + SCROLL_TO
            + """
  scrollTo(3600);
  const ending = {
    ...chrome(),
    topRowClass: kids()[221].className,
    topRowText: kids()[221].textContent,
    botRowClass: kids()[240].className,
    botRowText: kids()[240].textContent,
  };
  scrollTo(8100);
  const starting = {
    ...chrome(),
    topRowClass: kids()[1].className,
    topRowText: kids()[1].textContent,
    botRowClass: kids()[70].className,
    botRowText: kids()[70].textContent,
    footClass: kids()[71].className,
  };
  return { ending, starting };
"""
        )

        ending = result["ending"]
        self.assertEqual(240, ending["counted"])
        self.assertEqual(1, ending["tops"])
        self.assertEqual(18, ending["mids"])
        self.assertEqual(1, ending["bots"])
        self.assertEqual(0, ending["feet"])
        self.assertEqual("ln dev capture-row cap-top", ending["topRowClass"])
        self.assertIn("cap-0", ending["topRowText"])
        self.assertEqual("ln dev capture-row cap-bot", ending["botRowClass"])
        self.assertIn("cap-19", ending["botRowText"])

        starting = result["starting"]
        self.assertEqual(239, starting["counted"])
        self.assertEqual(1, starting["tops"])
        self.assertEqual(68, starting["mids"])
        self.assertEqual(1, starting["bots"])
        self.assertEqual(1, starting["feet"])
        self.assertEqual("ln dev capture-row cap-top", starting["topRowClass"])
        self.assertIn("cap-30", starting["topRowText"])
        self.assertEqual("ln dev capture-row cap-bot", starting["botRowClass"])
        self.assertIn("cap-99", starting["botRowText"])
        self.assertEqual("cap-foot", starting["footClass"])

    def test_transcript_gap_renders_as_one_row_inside_a_historical_slice(self):
        result = run_ui_scenario(
            """
  const linux = term("slot0");
"""
            + SCROLL_TO
            + """
  for (let index = 0; index < 300; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `line-${index}` });
  }
  flushFrames();
  linux.clientHeight = 400;
  linux.scrollHeight = 100000;
  linux.scrollTop = 100;
  linux.dispatch("scroll");
  for (let index = 0; index < 40; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `omitted-${index}` });
  }
  linux.scrollTop = 99600;
  linux.dispatch("scroll");
  for (let index = 0; index < 500; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `tail-${index}` });
  }
  flushFrames();
  linux.scrollTop = 100;
  linux.dispatch("scroll");
  scrollTo(5400);
  const rows = linux.children;
  return {
    children: rows.length,
    counted: rows.filter((c) => c.classList.contains("ln")).length,
    gaps: rows.filter((c) => c.className === "ln gap").length,
    gapClass: rows[121].className,
    gapText: rows[121].textContent,
    beforeGap: rows[120].textContent,
    afterGap: rows[122].textContent,
    firstText: rows[1].textContent,
    retained: paneModelSpies[0].countedSize(),
  };
"""
        )

        self.assertEqual(242, result["children"])
        self.assertEqual(240, result["counted"])
        self.assertEqual(1, result["gaps"])
        self.assertEqual("ln gap", result["gapClass"])
        self.assertEqual(
            "— 8 lines in session log, not in this view —",
            result["gapText"],
        )
        self.assertIn("line-299", result["beforeGap"])
        self.assertIn("omitted-8", result["afterGap"])
        self.assertIn("line-180", result["firstText"])
        self.assertEqual(833, result["retained"])

    def test_detach_and_rewindow_keep_the_top_visible_row_pinned(self):
        result = run_ui_scenario(
            """
  const linux = term("slot0");
  for (let index = 0; index < 1000; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `line-${index}` });
  }
  flushFrames();
  linux.clientHeight = 400;
  linux.scrollHeight = 18000;
  linux.scrollTop = 100;
  const attached = { scrollTop: linux.scrollTop, firstText: linux.children[0].textContent };
  linux.dispatch("scroll");
  const detached = { scrollTop: linux.scrollTop, top: linux.children[0].style.height };
  flushFrames();
  const windowed = { scrollTop: linux.scrollTop, top: linux.children[0].style.height };
  linux.scrollTop = 11700;
  linux.dispatch("scroll");
  flushFrames();
  const shifted = { scrollTop: linux.scrollTop, top: linux.children[0].style.height };
  return { attached, detached, windowed, shifted };
"""
        )

        # Attached: 100px into a window whose first row is retained entry 760.
        self.assertEqual(100, result["attached"]["scrollTop"])
        self.assertIn("line-760", result["attached"]["firstText"])
        # Detaching inserts 13680px of history above that row, so the row keeps its
        # position only if scrollTop moves by exactly the same amount.
        self.assertEqual("13680px", result["detached"]["top"])
        self.assertEqual(13780, result["detached"]["scrollTop"])
        # Re-windowing moves the slice but not the pixel the operator is looking at:
        # entry 765 starts at 13770px, and the viewport stays 10px into it.
        self.assertEqual("11610px", result["windowed"]["top"])
        self.assertEqual(13780, result["windowed"]["scrollTop"])
        self.assertEqual("9540px", result["shifted"]["top"])
        self.assertEqual(11700, result["shifted"]["scrollTop"])

    def test_zero_output_feet_do_not_move_the_anchor_on_detach_and_rewindow(self):
        for foot_count in (1, 3):
            with self.subTest(foot_count=foot_count):
                result = run_ui_scenario(
                    MEASURED_ROWS
                    + f"""
  globalThis.measureElementRect = (row) => {{
    const parent = row.parentNode;
    const height = row.offsetHeight;
    if (!parent) return {{ top: 0, left: 0, right: 0, bottom: height, width: 0, height }};
    let top = -parent.scrollTop;
    for (const sibling of parent.children) {{
      if (sibling === row) break;
      top += sibling.className === "transcript-spacer"
        ? Number.parseFloat(sibling.style.height || "0")
        : sibling.offsetHeight;
    }}
    return {{ top, left: 0, right: 0, bottom: top + height, width: 0, height }};
  }};
  const linux = term("slot0");
  for (let index = 0; index < 850; index += 1) {{
    send({{ type: "line", target: "linux", direction: "<<<", text: `line-${{index}}` }});
  }}
  for (let index = 0; index < {foot_count}; index += 1) {{
    send({{ type: "exec", phase: "start", id: index + 1, target: "linux", cmd: "silent" }});
    send({{
      type: "exec", phase: "end", id: index + 1, target: "linux",
      ended_by: "idle", ms: 1, bytes: 0, truncated: false, ok: true,
    }});
  }}
  for (let index = 850; index < 1000; index += 1) {{
    send({{ type: "line", target: "linux", direction: "<<<", text: `line-${{index}}` }});
  }}
  flushFrames();
  linux.clientHeight = 400;
  linux.scrollHeight = 18000;
  linux.scrollTop = 100;
  const rowFor = (text) => linux.children.find((row) => row.textContent.includes(text));
  const before = rowFor("line-766").getBoundingClientRect().top;
  linux.dispatch("scroll");
  flushFrames();
  const after = rowFor("line-766").getBoundingClientRect().top;
  return {{ before, after, drift: Math.abs(after - before) }};
"""
                )

                self.assertLessEqual(
                    result["drift"],
                    2,
                    f"{foot_count} zero-output Exec(s) moved the anchor from "
                    f"{result['before']}px to {result['after']}px",
                )

    def test_expanding_a_row_corrects_the_index_without_moving_the_anchor(self):
        result = run_ui_scenario(
            """
  globalThis.onCreateElement = (el) => {
    el.scrollHeight = 72;
    el.clientHeight = 24;
  };
  globalThis.measureRowHeight = (row) =>
    String(row.className).split(" ").includes("expanded") ? 54 : 18;
"""
            + DETACH_1000
            + """
  const rows = linux.children;
  const target = rows[56];
  const toggle = target.children[2];
  const before = {
    scrollTop: linux.scrollTop,
    top: rows[0].style.height,
    bottom: rows[rows.length - 1].style.height,
    rowClass: target.className,
  };
  linux.dispatch("click", { target: toggle });
  return {
    before,
    scrollTop: linux.scrollTop,
    top: rows[0].style.height,
    bottom: rows[rows.length - 1].style.height,
    rowClass: target.className,
    targetText: target.textContent,
  };
"""
        )

        self.assertIn("line-700", result["targetText"])
        self.assertNotIn("expanded", result["before"]["rowClass"].split(" "))
        self.assertIn("expanded", result["rowClass"].split(" "))
        self.assertEqual(13780, result["before"]["scrollTop"])
        # Entry 700 grew 18px -> 54px above the anchor, so the anchor row only stays put
        # if scrollTop absorbs the same 36px. The spacers bound unchanged content.
        self.assertEqual(13816, result["scrollTop"])
        self.assertEqual(result["before"]["top"], result["top"])
        self.assertEqual(result["before"]["bottom"], result["bottom"])

    def test_flood_while_detached_leaves_history_alone_and_recovers_once_at_the_bottom(self):
        result = run_ui_scenario(
            DETACH_1000
            + """
  const texts = () => linux.children.map((c) => c.textContent);
  const before = texts();
  for (let index = 0; index < 100; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `flood-${index}` });
  }
  flushFrames();
  const during = texts();
  const detached = {
    spacers: linux.children.filter((c) => c.className === "transcript-spacer").length,
    firstText: linux.children[1].textContent,
  };
  linux.scrollTop = 17600;
  linux.dispatch("scroll");
  flushFrames();
  send({ type: "line", target: "linux", direction: "<<<", text: "after-reattach" });
  const rows = linux.children;
  const rowTexts = texts();
  return {
    unchanged: JSON.stringify(before) === JSON.stringify(during),
    detached,
    spacers: rows.filter((c) => c.className === "transcript-spacer").length,
    counted: rows.filter((c) => c.classList.contains("ln")).length,
    gaps: rows.filter((c) => c.className === "ln gap").length,
    gapIndex: rows.findIndex((c) => c.className === "ln gap"),
    gapText: rowTexts[rows.findIndex((c) => c.className === "ln gap")],
    firstText: rowTexts[0],
    lastText: rowTexts[rowTexts.length - 1],
    text: linux.textContent,
  };
"""
        )

        self.assertTrue(result["unchanged"])
        self.assertEqual(2, result["detached"]["spacers"])
        self.assertIn("line-645", result["detached"]["firstText"])
        self.assertEqual(0, result["spacers"])
        self.assertEqual(240, result["counted"])
        self.assertEqual(1, result["gaps"])
        self.assertEqual(
            "— 68 lines in session log, not in this view —",
            result["gapText"],
        )
        self.assertIn("line-999", result["text"])
        self.assertIn("flood-68", result["text"])
        self.assertNotIn("flood-67", result["text"])
        self.assertIn("after-reattach", result["lastText"])

    def test_tightening_retention_while_detached_clamps_history_without_a_gap(self):
        result = run_ui_scenario(
            DETACH_1000
            + """
  document.getElementById("live-depth-500").dispatch("click");
  const rows = linux.children;
  return {
    children: rows.length,
    counted: rows.filter((c) => c.classList.contains("ln")).length,
    gaps: rows.filter((c) => c.className === "ln gap").length,
    spacers: rows.filter((c) => c.className === "transcript-spacer").length,
    top: rows[0].style.height,
    bottom: rows[rows.length - 1].style.height,
    firstText: rows[1].textContent,
    lastText: rows[rows.length - 2].textContent,
    retained: paneModelSpies[0].countedSize(),
    scrollTop: linux.scrollTop,
  };
"""
        )

        self.assertEqual(242, result["children"])
        self.assertEqual(240, result["counted"])
        self.assertEqual(0, result["gaps"])
        self.assertEqual(2, result["spacers"])
        self.assertEqual(500, result["retained"])
        # The 500 oldest entries left the model, so the same lines are still on screen
        # with 500 fewer estimated rows (9000px) above them.
        self.assertEqual("2610px", result["top"])
        self.assertEqual("2070px", result["bottom"])
        self.assertIn("line-645", result["firstText"])
        self.assertIn("line-884", result["lastText"])
        self.assertEqual(4780, result["scrollTop"])

    def test_clear_drops_history_and_panes_hold_independent_virtual_state(self):
        result = run_ui_scenario(
            """
  const linux = term("slot0");
  const rtos = term("slot1");
  for (let index = 0; index < 1000; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `line-${index}` });
    send({ type: "line", target: "rtos", direction: "<<<", text: `rtos-${index}` });
  }
  flushFrames();
  linux.clientHeight = 400;
  linux.scrollHeight = 18000;
  linux.scrollTop = 100;
  linux.dispatch("scroll");
  flushFrames();
  const spacers = (el) => el.children.filter((c) => c.className === "transcript-spacer").length;
  send({ type: "line", target: "rtos", direction: "<<<", text: "rtos-live" });
  send({ type: "line", target: "linux", direction: "<<<", text: "linux-omitted" });
  const independent = {
    linuxSpacers: spacers(linux),
    rtosSpacers: spacers(rtos),
    rtosRows: rtos.children.length,
    rtosLive: rtos.children[rtos.children.length - 1].textContent,
    linuxOmitted: linux.textContent.includes("linux-omitted"),
  };
  document.getElementById("btn-clear").dispatch("click");
  const cleared = { linux: linux.children.length, rtos: rtos.children.length };
  send({ type: "line", target: "linux", direction: "<<<", text: "after-clear" });
  return {
    independent,
    cleared,
    linuxAfter: linux.children.length,
    linuxSpacersAfter: spacers(linux),
    linuxText: linux.textContent,
    retained: paneModelSpies[0].countedSize(),
  };
"""
        )

        self.assertEqual(2, result["independent"]["linuxSpacers"])
        self.assertEqual(0, result["independent"]["rtosSpacers"])
        self.assertEqual(240, result["independent"]["rtosRows"])
        self.assertIn("rtos-live", result["independent"]["rtosLive"])
        self.assertFalse(result["independent"]["linuxOmitted"])
        self.assertEqual({"linux": 0, "rtos": 0}, result["cleared"])
        self.assertEqual(1, result["linuxAfter"])
        self.assertEqual(0, result["linuxSpacersAfter"])
        self.assertIn("after-clear", result["linuxText"])
        self.assertEqual(1, result["retained"])

    def test_scroll_bursts_coalesce_into_one_frame_without_rescanning_retention(self):
        result = run_ui_scenario(
            DETACH_1000
            + """
  const before = { slice: paneReads.slice, entries: paneReads.entries };
  const childrenBefore = childrenReads;
  for (const top of [13000, 12800, 12600, 12400, 12200, 12000, 11800, 11600, 11400, 11200, 11000, 10800]) {
    linux.scrollTop = top;
    linux.dispatch("scroll");
  }
  const duringBurst = { slice: paneReads.slice - before.slice, frames: frameCallbacks.length };
  flushFrames();
  const scans = childrenReads - childrenBefore;
  return {
    duringBurst,
    scans,
    slice: paneReads.slice - before.slice,
    entries: paneReads.entries - before.entries,
    counted: linux.children.filter((c) => c.classList.contains("ln")).length,
  };
"""
        )

        self.assertEqual(0, result["duringBurst"]["slice"])
        self.assertEqual(1, result["duringBurst"]["frames"])
        self.assertEqual(1, result["slice"])
        self.assertEqual(0, result["entries"])
        self.assertEqual(0, result["scans"])
        self.assertEqual(240, result["counted"])

    def test_sealing_a_capture_while_detached_keeps_rows_and_model_aligned(self):
        result = run_ui_scenario(
            DETACH_OPEN_CAPTURE
            + SCROLL_TO
            + ALIGNED_WITH
            + """
  send({
    type: "exec", phase: "end", id: 7, target: "linux",
    ended_by: "idle", ms: 12, bytes: 100, truncated: false, ok: true,
  });
  flushFrames();
  const sealed = {
    ...chrome(),
    spacers: kids().filter((c) => c.className === "transcript-spacer").length,
    top: kids()[0].style.height,
    bottom: kids()[kids().length - 1].style.height,
    scrollTop: linux.scrollTop,
    aligned: alignedWith(660, 900),
  };
  scrollTo(15500);
  const rewindowed = {
    ...chrome(),
    top: kids()[0].style.height,
    bottom: kids()[kids().length - 1].style.height,
    footClass: kids()[240].className,
    footText: kids()[240].textContent,
    lastCapText: kids()[239].textContent,
    firstText: kids()[1].textContent,
    aligned: alignedWith(661, 901),
  };
  linux.scrollTop = 15818;
  linux.dispatch("scroll");
  flushFrames();
  const reattached = {
    ...chrome(),
    spacers: kids().filter((c) => c.className === "transcript-spacer").length,
    footClass: kids()[239].className,
    firstText: kids()[0].textContent,
    aligned: alignedWith(661, 901),
  };
  send({ type: "line", target: "linux", direction: "<<<", text: "after-reattach" });
  return {
    sealed,
    rewindowed,
    reattached,
    afterReattachText: kids()[kids().length - 1].textContent,
    liveChildren: kids().length,
  };
"""
        )

        # Sealing while detached must leave the historical DOM exactly as the slice
        # describes it: the footer is a retained entry at model position 900, which is
        # outside the materialized [660, 900), so it is not drawn yet.
        self.assertEqual("aligned", result["sealed"]["aligned"])
        self.assertEqual(242, result["sealed"]["children"])
        self.assertEqual(240, result["sealed"]["counted"])
        self.assertEqual(0, result["sealed"]["feet"])
        self.assertEqual(2, result["sealed"]["spacers"])
        self.assertEqual("11880px", result["sealed"]["top"])
        # The retained model grew by that footer, so the virtual extent has to grow with
        # it. A stale bottom spacer is what puts the true virtual bottom one entry too
        # high and reattaches Follow early.
        self.assertEqual("18px", result["sealed"]["bottom"])
        self.assertEqual(12380, result["sealed"]["scrollTop"])

        # Re-windowing onto the tail draws the footer from the model, exactly once, in
        # its retained position right after the capture's last row.
        self.assertEqual("aligned", result["rewindowed"]["aligned"])
        self.assertEqual(242, result["rewindowed"]["children"])
        self.assertEqual(239, result["rewindowed"]["counted"])
        self.assertEqual(1, result["rewindowed"]["feet"])
        self.assertEqual(1, result["rewindowed"]["tops"])
        self.assertEqual(98, result["rewindowed"]["mids"])
        self.assertEqual(1, result["rewindowed"]["bots"])
        self.assertEqual("11898px", result["rewindowed"]["top"])
        self.assertEqual("0px", result["rewindowed"]["bottom"])
        self.assertEqual("cap-foot", result["rewindowed"]["footClass"])
        self.assertIn("closed on idle", result["rewindowed"]["footText"])
        self.assertIn("cap-99", result["rewindowed"]["lastCapText"])
        self.assertIn("pre-661", result["rewindowed"]["firstText"])

        self.assertEqual("aligned", result["reattached"]["aligned"])
        self.assertEqual(0, result["reattached"]["spacers"])
        self.assertEqual(240, result["reattached"]["children"])
        self.assertEqual(1, result["reattached"]["feet"])
        self.assertEqual("cap-foot", result["reattached"]["footClass"])
        self.assertIn("pre-661", result["reattached"]["firstText"])
        self.assertIn("after-reattach", result["afterReattachText"])
        self.assertEqual(241, result["liveChildren"])

    def test_capture_spanning_detach_reattaches_as_one_run_without_a_gap(self):
        result = run_ui_scenario(
            DETACH_SPANNING_CAPTURE
            + SCROLL_TO
            + CAPTURE_SHAPE
            + """
  scrollTo(3600);
  scrollTo(15500);
  const historical = shape();
  bufferAndSeal(5);
  reattach();
  const model = paneModelSpies[0]
    .slice(0, paneModelSpies[0].size())
    .map((e) => (e.kind === "foot" ? "foot" : e.captureId === 7 ? "cap" : "line"));
  return {
    historical,
    shape: shape(),
    jump: jump(),
    model: {
      caps: model.filter((k) => k === "cap").length,
      feet: model.filter((k) => k === "foot").length,
      contiguous:
        model.lastIndexOf("cap") - model.indexOf("cap") ===
        model.filter((k) => k === "cap").length - 1,
      footLast: model.indexOf("foot") === model.length - 1,
    },
  };
"""
        )

        # The history renderer owns the capture's rows before the buffered ones replay.
        self.assertEqual(1, result["historical"]["capTops"])
        self.assertEqual(100, result["historical"]["capRows"])

        # Replay has to continue that one run rather than open a second box below it.
        self.assertEqual(0, result["shape"]["gaps"])
        self.assertEqual(1, result["shape"]["capTops"])
        self.assertEqual(1, result["shape"]["capBots"])
        self.assertEqual(1, result["shape"]["feet"])
        self.assertTrue(result["shape"]["contiguous"])
        self.assertEqual(105, result["shape"]["capRows"])
        self.assertIn("cap-0", result["shape"]["firstCapText"])
        self.assertIn("buffered-4", result["shape"]["lastCapText"])
        # The footer seals the whole run, so it sits directly under its last row.
        self.assertEqual(
            result["shape"]["topAt"] + result["shape"]["capRows"],
            result["shape"]["footAt"],
        )

        self.assertIn("jump-hit", result["jump"]["node"])
        self.assertIn("cap-0", result["jump"]["row"])
        self.assertIn("cap-top", result["jump"]["rowClass"].split(" "))

        # Retention has to agree, since a later detach re-draws this region from it.
        self.assertEqual(105, result["model"]["caps"])
        self.assertEqual(1, result["model"]["feet"])
        self.assertTrue(result["model"]["contiguous"])
        self.assertTrue(result["model"]["footLast"])

    def test_capture_spanning_detach_moves_after_its_gap_as_one_run(self):
        result = run_ui_scenario(
            DETACH_SPANNING_CAPTURE
            + SCROLL_TO
            + CAPTURE_SHAPE
            + """
  scrollTo(3600);
  scrollTo(15500);
  bufferAndSeal(40);
  reattach();
  const rows = linux.children;
  return {
    shape: shape(),
    jump: jump(),
    gapText: rows[rows.findIndex((c) => c.className === "ln gap")].textContent,
  };
"""
        )

        # 40 buffered captured rows overflow the 32-row tail, so 8 are evicted and the
        # recovery Gap appears. The already materialized run has to move below it whole.
        self.assertEqual(1, result["shape"]["gaps"])
        self.assertEqual(
            "— 8 lines in session log, not in this view —",
            result["gapText"],
        )
        self.assertLess(result["shape"]["gapAt"], result["shape"]["topAt"])
        self.assertEqual(1, result["shape"]["capTops"])
        self.assertEqual(1, result["shape"]["capBots"])
        self.assertEqual(1, result["shape"]["feet"])
        self.assertTrue(result["shape"]["contiguous"])
        self.assertEqual(132, result["shape"]["capRows"])
        self.assertIn("cap-0", result["shape"]["firstCapText"])
        self.assertIn("buffered-39", result["shape"]["lastCapText"])
        self.assertEqual(
            result["shape"]["topAt"] + result["shape"]["capRows"],
            result["shape"]["footAt"],
        )

        self.assertIn("jump-hit", result["jump"]["node"])
        self.assertIn("cap-0", result["jump"]["row"])
        self.assertIn("cap-top", result["jump"]["rowClass"].split(" "))

    def test_second_detach_over_a_recovered_capture_shows_the_model_visual_order(self):
        result = run_ui_scenario(
            MEASURED_ROWS
            + DETACH_SPANNING_CAPTURE
            + SCROLL_TO
            + CAPTURE_SHAPE
            + """
  scrollTo(3600);
  scrollTo(15500);
  bufferAndSeal(40);
  reattach();
  const live = shape();
  const model = paneModelSpies[0]
    .slice(0, paneModelSpies[0].countedSize() + 8)
    .map((e) => (e.kind === "gap" ? "gap" : e.kind === "foot" ? "foot" : e.captureId === 7 ? "cap" : "line"));
  const gapAt = model.indexOf("gap");
  const capFrom = model.indexOf("cap");
  const capTo = model.lastIndexOf("cap");
  const footAt = model.indexOf("foot");
  // Detach again. The pane ignores the scroll that leaves the tail and takes the next
  // one as the genuine gesture, at which point history mode adopts the rows already
  // materialized rather than re-rendering them.
  scrollTo(8000);
  scrollTo(1000);
  // Every row the pane is holding right now is branded, so a slice that still carries
  // the brand would mean the renderer never ran and these assertions are reading
  // leftover live rows.
  linux.children.forEach((row) => { row.__live = true; });
  const beforeReads = paneReads.slice;
  // Both of these land outside the materialized band, so each one has to draw a new
  // slice straight from the retained model.
  scrollTo(5000);
  scrollTo(15000);
  const revisited = shape();
  return {
    live,
    model: {
      gapAt,
      capFrom,
      capTo,
      footAt,
      gaps: model.filter((k) => k === "gap").length,
      feet: model.filter((k) => k === "foot").length,
      caps: model.filter((k) => k === "cap").length,
      contiguous: capTo - capFrom === model.filter((k) => k === "cap").length - 1,
    },
    rendered: {
      reads: paneReads.slice - beforeReads,
      carriedOver: linux.children.filter(
        (row) => row.__live === true && row.className !== "transcript-spacer",
      ).length,
      spacersKept: linux.children.filter(
        (row) => row.__live === true && row.className === "transcript-spacer",
      ).length,
      rows: linux.children.length,
    },
    revisited,
    jump: jump(),
  };
"""
        )

        # The history renderer really ran: two re-windows, each reading the model, and not
        # one row object survived them. What follows is drawn from retention.
        self.assertEqual(2, result["rendered"]["reads"])
        self.assertEqual(0, result["rendered"]["carriedOver"])
        self.assertEqual(242, result["rendered"]["rows"])
        # The two spacers are the frame around the slice and are meant to be reused.
        self.assertEqual(2, result["rendered"]["spacersKept"])

        # Live recovery: one Gap, one run, one seal.
        self.assertEqual(1, result["live"]["gaps"])
        self.assertEqual(1, result["live"]["capTops"])
        self.assertEqual(1, result["live"]["capBots"])
        self.assertEqual(1, result["live"]["feet"])
        self.assertTrue(result["live"]["contiguous"])

        # The retained model carries that same order, which is the whole point: the Gap
        # first, then one unbroken run, then the seal after every replayed row.
        self.assertEqual(1, result["model"]["gaps"])
        self.assertEqual(1, result["model"]["feet"])
        self.assertEqual(132, result["model"]["caps"])
        self.assertTrue(result["model"]["contiguous"])
        self.assertLess(result["model"]["gapAt"], result["model"]["capFrom"])
        self.assertLess(result["model"]["capTo"], result["model"]["footAt"])

        # Re-windowing over the region draws from the model, so it must agree with what
        # the operator saw live rather than showing a second box or an early seal.
        self.assertEqual(1, result["revisited"]["gaps"])
        self.assertEqual(1, result["revisited"]["capTops"])
        self.assertEqual(1, result["revisited"]["capBots"])
        self.assertEqual(1, result["revisited"]["feet"])
        self.assertTrue(result["revisited"]["contiguous"])
        self.assertEqual(132, result["revisited"]["capRows"])
        self.assertIn("cap-0", result["revisited"]["firstCapText"])
        self.assertIn("buffered-39", result["revisited"]["lastCapText"])
        self.assertLess(result["revisited"]["gapAt"], result["revisited"]["topAt"])
        self.assertEqual(
            result["revisited"]["topAt"] + result["revisited"]["capRows"],
            result["revisited"]["footAt"],
        )

        # Trace Jump still anchors the unified top even though the slice was re-rendered.
        self.assertIn("jump-hit", result["jump"]["node"])
        self.assertIn("cap-0", result["jump"]["row"])
        self.assertIn("cap-top", result["jump"]["rowClass"].split(" "))

    def test_a_row_interleaved_into_a_running_capture_stays_below_the_run(self):
        result = run_ui_scenario(
            MEASURED_ROWS
            + DETACH_SPANNING_CAPTURE
            + SCROLL_TO
            + CAPTURE_SHAPE
            + """
  const kinds = () => paneModelSpies[0]
    .slice(0, paneModelSpies[0].size())
    .map((e) => (e.kind === "foot" ? "foot" : e.captureId === 7 ? "cap" : e.text));
  const runShape = () => {
    const model = kinds();
    const caps = model.filter((k) => k === "cap").length;
    return {
      caps,
      contiguous: model.lastIndexOf("cap") - model.indexOf("cap") === caps - 1,
      noteBelowRun: model.indexOf("interleaved-note") > model.lastIndexOf("cap"),
      typedBelowRun: model.indexOf("typed-mid-capture") > model.lastIndexOf("cap"),
      footAt: model.indexOf("foot"),
      capTo: model.lastIndexOf("cap"),
      noteAt: model.indexOf("interleaved-note"),
    };
  };
  scrollTo(3600);
  scrollTo(15500);
  for (let index = 0; index < 5; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `buffered-${index}` });
  }
  // Reattach with the Exec still running, then let a system row and an Operator write
  // barge in before more captured output arrives.
  reattach();
  send({ type: "line", target: "linux", direction: "---", text: "interleaved-note" });
  send({ type: "line", target: "linux", direction: ">>>", text: "typed-mid-capture" });
  send({ type: "line", target: "linux", direction: "<<<", text: "after-note-0" });
  send({ type: "line", target: "linux", direction: "<<<", text: "after-note-1" });
  flushFrames();
  const live = shape();
  const liveModel = runShape();

  // Detach a second time. The pane ignores the scroll that leaves the tail, adopts the
  // materialized rows on the next one, and only then can a scroll outside that band
  // force the renderer to draw a fresh slice from retention.
  scrollTo(8000);
  scrollTo(1000);
  linux.children.forEach((row) => { row.__live = true; });
  const beforeReads = paneReads.slice;
  scrollTo(5000);
  scrollTo(15000);
  const rendered = {
    reads: paneReads.slice - beforeReads,
    carriedOver: linux.children.filter(
      (row) => row.__live === true && row.className !== "transcript-spacer",
    ).length,
  };
  const historical = shape();
  const rows = linux.children;
  const capIdx = rows
    .map((c, i) => (c.classList.contains("capture-row") ? i : -1))
    .filter((i) => i >= 0);
  const historicalOrder = {
    noteAt: rows.findIndex((c) => c.textContent.includes("interleaved-note")),
    typedAt: rows.findIndex((c) => c.textContent.includes("typed-mid-capture")),
    capTo: capIdx[capIdx.length - 1],
    lastCapText: rows[capIdx[capIdx.length - 1]].textContent,
  };
  const jumped = jump();

  // Seal while the pane is still detached: the footer is a model entry, so it has to
  // land on the run rather than under whatever happens to be at the tail.
  send({
    type: "exec", phase: "end", id: 7, target: "linux",
    ended_by: "idle", ms: 12, bytes: 100, truncated: false, ok: true,
  });
  flushFrames();
  // A seal that lands inside the materialized band is still only drawn when the slice is
  // rendered again, so re-window across it before reading the footer's position.
  scrollTo(5000);
  scrollTo(15000);
  const sealedRows = linux.children;
  const sealedFootAt = sealedRows.findIndex((c) => c.className === "cap-foot");
  return {
    live,
    liveModel,
    rendered,
    historical,
    historicalOrder,
    jump: jumped,
    sealedModel: runShape(),
    sealed: {
      ...shape(),
      aboveFoot: sealedFootAt < 0 ? "" : sealedRows[sealedFootAt - 1].textContent,
      belowFoot: sealedFootAt < 0 ? "" : sealedRows[sealedFootAt + 1].textContent,
    },
  };
"""
        )

        # Live: one box, still running, and the two non-captured rows sit below the whole
        # run rather than splitting it.
        self.assertEqual(1, result["live"]["capTops"])
        self.assertEqual(0, result["live"]["feet"])
        self.assertEqual(107, result["live"]["capRows"])
        self.assertTrue(result["live"]["contiguous"])
        self.assertIn("cap-0", result["live"]["firstCapText"])
        self.assertIn("after-note-1", result["live"]["lastCapText"])

        # Retention has to say the same thing, since that is what a second detach draws.
        self.assertEqual(107, result["liveModel"]["caps"])
        self.assertTrue(result["liveModel"]["contiguous"])
        self.assertTrue(result["liveModel"]["noteBelowRun"])
        self.assertTrue(result["liveModel"]["typedBelowRun"])

        # The re-windows genuinely re-rendered from the model, replacing every row.
        self.assertEqual(2, result["rendered"]["reads"])
        self.assertEqual(0, result["rendered"]["carriedOver"])

        # Historical DOM: still one box, with the interleaved rows still below it.
        self.assertEqual(1, result["historical"]["capTops"])
        self.assertEqual(0, result["historical"]["feet"])
        self.assertTrue(result["historical"]["contiguous"])
        self.assertEqual(107, result["historical"]["capRows"])
        self.assertIn("cap-0", result["historical"]["firstCapText"])
        self.assertIn("after-note-1", result["historicalOrder"]["lastCapText"])
        self.assertGreater(
            result["historicalOrder"]["noteAt"], result["historicalOrder"]["capTo"]
        )
        self.assertGreater(
            result["historicalOrder"]["typedAt"], result["historicalOrder"]["capTo"]
        )

        self.assertIn("jump-hit", result["jump"]["node"])
        self.assertIn("cap-0", result["jump"]["row"])
        self.assertIn("cap-top", result["jump"]["rowClass"].split(" "))

        # Sealing closes the run itself: the footer follows the capture's last line, and
        # the rows that barged in stay below it.
        self.assertEqual(1, result["sealedModel"]["footAt"] - result["sealedModel"]["capTo"])
        self.assertGreater(
            result["sealedModel"]["noteAt"], result["sealedModel"]["footAt"]
        )
        self.assertEqual(1, result["sealed"]["feet"])
        self.assertEqual(1, result["sealed"]["capTops"])
        self.assertTrue(result["sealed"]["contiguous"])
        self.assertIn("after-note-1", result["sealed"]["aboveFoot"])
        self.assertIn("interleaved-note", result["sealed"]["belowFoot"])

    def test_reattaching_drops_a_footer_whose_capture_rows_are_no_longer_retained(self):
        result = run_ui_scenario(
            """
  document.getElementById("live-depth-500").dispatch("click");
  const linux = term("slot0");
  send({ type: "exec", phase: "start", id: 9, target: "linux", cmd: "one-liner" });
  send({ type: "line", target: "linux", direction: "<<<", text: "capture-line-0" });
  for (let index = 0; index < 499; index += 1) {
    send({ type: "line", target: "linux", direction: "---", text: `filler-${index}` });
  }
  flushFrames();
  linux.clientHeight = 400;
  linux.scrollHeight = 9000;
  linux.scrollTop = 100;
  linux.dispatch("scroll");
  flushFrames();
  send({ type: "line", target: "linux", direction: "<<<", text: "buffered-into-capture" });
  send({
    type: "exec", phase: "end", id: 9, target: "linux",
    ended_by: "idle", ms: 5, bytes: 14, truncated: false, ok: true,
  });
  flushFrames();
  linux.scrollTop = 8000;
  linux.dispatch("scroll");
  flushFrames();
  const detached = {
    feet: linux.children.filter((c) => c.className === "cap-foot").length,
    capRows: linux.children.filter((c) => c.classList.contains("capture-row")).length,
    rows: linux.children.filter((c) => c.className !== "transcript-spacer").length,
  };
  linux.scrollTop = 8600;
  linux.dispatch("scroll");
  flushFrames();
  const rows = linux.children;
  const footAt = rows.findIndex((c) => c.className === "cap-foot");
  return {
    detached,
    feet: rows.filter((c) => c.className === "cap-foot").length,
    footAt,
    aboveFoot: footAt < 0 ? "" : rows[footAt - 1].className,
    aboveFootText: footAt < 0 ? "" : rows[footAt - 1].textContent,
    retainedFeet: paneModelSpies[0]
      .slice(0, paneModelSpies[0].size())
      .filter((entry) => entry.kind === "foot").length,
  };
"""
        )

        # The seal closes its own run, so it is retained beside capture 9's single line
        # near the top of the transcript — far outside the window a pane scrolled to the
        # bottom is showing. Neither the run nor its seal is drawn here.
        self.assertEqual(0, result["detached"]["feet"])
        self.assertEqual(0, result["detached"]["capRows"])
        self.assertEqual(240, result["detached"]["rows"])
        self.assertEqual(1, result["retainedFeet"])
        self.assertEqual(1, result["feet"])
        self.assertIn("capture-row", result["aboveFoot"].split(" "))
        self.assertIn("buffered-into-capture", result["aboveFootText"])

    def test_reattached_history_capture_anchor_survives_followed_trimming(self):
        result = run_ui_scenario(
            """
  const linux = term("slot0");
  for (let index = 0; index < 100; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `pre-${index}` });
  }
  send({ type: "exec", phase: "start", id: 7, target: "linux", cmd: "dmesg" });
  for (let index = 0; index < 300; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `cap-${index}` });
  }
  send({
    type: "exec", phase: "end", id: 7, target: "linux",
    ended_by: "idle", ms: 12, bytes: 300, truncated: false, ok: true,
  });
  for (let index = 0; index < 50; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `post-${index}` });
  }
  flushFrames();
  linux.clientHeight = 400;
  linux.scrollHeight = 8118;
  linux.scrollTop = 100;
  linux.dispatch("scroll");
  flushFrames();
  const detached = { firstText: linux.children[1].textContent };
  linux.scrollTop = 7718;
  linux.dispatch("scroll");
  flushFrames();
  const headState = () => ({
    text: linux.children[0].textContent,
    className: linux.children[0].className,
  });
  const jump = () => {
    const node = document.getElementById("spine-body").children[0];
    node.dispatch("click");
    const hit = linux.children.find((c) => c.classList.contains("jump-flash"));
    return {
      node: node.className,
      row: hit ? hit.textContent : null,
      rowClass: hit ? hit.className : null,
      spacers: linux.children.filter((c) => c.className === "transcript-spacer").length,
    };
  };
  const reattach = () => {
    linux.scrollTop = linux.scrollHeight;
    linux.dispatch("scroll");
    flushFrames();
  };
  const feed = (count, tag) => {
    for (let index = 0; index < count; index += 1) {
      send({ type: "line", target: "linux", direction: "<<<", text: `${tag}-${index}` });
    }
    flushFrames();
  };
  const followed = headState();
  const afterReattach = jump();
  reattach();
  feed(2, "tail");
  const afterTrim = headState();
  feed(188, "more");
  const evicted = {
    capRows: linux.children.filter((c) => c.classList.contains("capture-row")).length,
    feet: linux.children.filter((c) => c.className === "cap-foot").length,
    spacers: linux.children.filter((c) => c.className === "transcript-spacer").length,
  };
  linux.scrollHeight = 11538;
  const afterEviction = jump();
  return { detached, followed, afterReattach, afterTrim, evicted, afterEviction };
"""
        )

        # The window the operator scrolled to is drawn by the history renderer, so the
        # capture's Trace Jump anchor is one of its rows rather than a followed one.
        self.assertIn("pre-95", result["detached"]["firstText"])

        # Reattaching adopts a slice that starts inside the capture, so the anchor the
        # followed window holds is a fragment head.
        self.assertIn("cap-111", result["followed"]["text"])
        self.assertIn("cap-top", result["followed"]["className"].split(" "))
        # The jump is answerable from that fragment, and must refuse it: cap-0 is still
        # retained, so that is the line the operator asked for.
        self.assertIn("jump-hit", result["afterReattach"]["node"])
        self.assertIn("cap-0", result["afterReattach"]["row"])
        self.assertIn("cap-top", result["afterReattach"]["rowClass"].split(" "))
        self.assertEqual(2, result["afterReattach"]["spacers"])

        # Trimming the anchor away must hand the anchor to the capture's next surviving
        # row. A historical row the followed window cannot account for leaves the index
        # pointing at a removed node, and the capture loses its chrome on screen.
        self.assertIn("cap-112", result["afterTrim"]["text"])
        self.assertIn("cap-top", result["afterTrim"]["className"].split(" "))

        # Once no row of the capture is materialized the anchor must be gone, not stale.
        self.assertEqual(0, result["evicted"]["capRows"])
        self.assertEqual(0, result["evicted"]["feet"])
        self.assertEqual(0, result["evicted"]["spacers"])
        # Retention still holds the whole capture, so the jump re-materializes it in a
        # detached history window rather than reporting a miss.
        self.assertIn("jump-hit", result["afterEviction"]["node"])
        self.assertIn("cap-0", result["afterEviction"]["row"])
        self.assertIn("cap-top", result["afterEviction"]["rowClass"].split(" "))
        self.assertEqual(2, result["afterEviction"]["spacers"])


# A sealed 100-line capture at the very top, then 600 lines that push it out of the
# followed window while retention keeps every entry. 701 retained entries, 12618px.
JUMP_CAPTURE_ABOVE = """
  const linux = term("slot0");
  send({ type: "exec", phase: "start", id: 7, target: "linux", cmd: "dmesg" });
  for (let index = 0; index < 100; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `cap-${index}` });
  }
  send({
    type: "exec", phase: "end", id: 7, target: "linux",
    ended_by: "idle", ms: 12, bytes: 100, truncated: false, ok: true,
  });
  for (let index = 0; index < 600; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `post-${index}` });
  }
  flushFrames();
  linux.clientHeight = 400;
  linux.scrollHeight = 12618;
"""

# 600 leading lines, the same sealed 100-line capture, then 600 trailing lines, with the
# pane already detached. 1301 retained entries, 23418px.
JUMP_CAPTURE_BELOW = """
  const linux = term("slot0");
  for (let index = 0; index < 600; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `pre-${index}` });
  }
  send({ type: "exec", phase: "start", id: 7, target: "linux", cmd: "dmesg" });
  for (let index = 0; index < 100; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `cap-${index}` });
  }
  send({
    type: "exec", phase: "end", id: 7, target: "linux",
    ended_by: "idle", ms: 12, bytes: 100, truncated: false, ok: true,
  });
  for (let index = 0; index < 600; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `post-${index}` });
  }
  flushFrames();
  linux.clientHeight = 400;
  linux.scrollHeight = 23418;
  linux.scrollTop = 100;
  linux.dispatch("scroll");
  flushFrames();
"""

# 993 leading lines, then a sealed 20-line capture and two trailing lines, with the pane
# already detached near the middle of retention. 1016 retained entries, 18288px, and the
# capture's first line sits at 17874px — 14px inside the last 400px viewport, so landing
# on it puts the pane within the tail tolerance without the operator going there.
JUMP_CAPTURE_NEAR_TAIL = """
  const linux = term("slot0");
  for (let index = 0; index < 993; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `pre-${index}` });
  }
  send({ type: "exec", phase: "start", id: 7, target: "linux", cmd: "dmesg" });
  for (let index = 0; index < 20; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `cap-${index}` });
  }
  send({
    type: "exec", phase: "end", id: 7, target: "linux",
    ended_by: "idle", ms: 12, bytes: 20, truncated: false, ok: true,
  });
  for (let index = 0; index < 2; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `post-${index}` });
  }
  flushFrames();
  linux.clientHeight = 400;
  linux.scrollHeight = 18288;
  linux.scrollTop = 100;
  linux.dispatch("scroll");
  flushFrames();
"""

# A jump reports both panes, because the thing a target-blind jump gets wrong is which
# pane it lands in rather than whether it lands at all.
JUMP_BY_SPINE_INDEX = """
  const flashesIn = (slot) =>
    term(slot).children.filter((c) => c.classList.contains("jump-flash"));
  const jumpTo = (index) => {
    const node = document.getElementById("spine-body").children[index];
    node.dispatch("click");
    const slot0 = flashesIn("slot0");
    const slot1 = flashesIn("slot1");
    return {
      node: node.className,
      slot0Flashes: slot0.length,
      slot1Flashes: slot1.length,
      slot0Row: slot0.length ? slot0[0].textContent : null,
      slot1Row: slot1.length ? slot1[0].textContent : null,
      rowClass: slot0.length ? slot0[0].className : slot1.length ? slot1[0].className : null,
    };
  };
  const paneState = (slot) => {
    const el = term(slot);
    const rows = el.children;
    return {
      children: rows.length,
      counted: rows.filter((c) => c.classList.contains("ln")).length,
      spacers: rows.filter((c) => c.className === "transcript-spacer").length,
      gaps: rows.filter((c) => c.className === "ln gap").length,
      top: rows.length ? rows[0].style.height : null,
      scrollTop: el.scrollTop,
    };
  };
"""


class TraceJumpIntoRetainedHistoryTest(unittest.TestCase):
    """A capture the operator can still reach is one retention still holds, not one the
    240-row window happens to be showing."""

    def test_jump_materializes_a_capture_above_the_followed_window(self):
        result = run_ui_scenario(
            JUMP_CAPTURE_ABOVE
            + JUMP_BY_SPINE_INDEX
            + """
  const before = paneState("slot0");
  const jump = jumpTo(0);
  const after = paneState("slot0");
  const flashed = flashesIn("slot0")[0];
  // A browser answers the jump's own scroll assignment with a scroll event and a frame;
  // neither may re-render the slice out from under the highlighted row.
  linux.dispatch("scroll");
  flushFrames();
  const rows = term("slot0").children;
  return {
    before,
    jump,
    after,
    settled: { ...paneState("slot0"), sameRow: flashesIn("slot0")[0] === flashed },
    firstText: rows[1].textContent,
    lastText: rows[rows.length - 2].textContent,
    retained: paneModelSpies[0].countedSize(),
  };
"""
        )

        # The capture is 700 entries above the tail, so the followed window cannot be
        # showing any of it.
        self.assertEqual(0, result["before"]["spacers"])
        self.assertEqual(240, result["before"]["counted"])
        self.assertEqual(700, result["retained"])

        self.assertIn("jump-hit", result["jump"]["node"])
        self.assertIn("cap-0", result["jump"]["slot0Row"])
        self.assertIn("cap-top", result["jump"]["rowClass"].split(" "))

        # Every virtualization invariant still holds around the materialized target.
        self.assertEqual(2, result["after"]["spacers"])
        self.assertEqual(242, result["after"]["children"])
        self.assertEqual(239, result["after"]["counted"])
        # Entry 0 is the target, so the slice starts at the very top of retention and the
        # pane sits exactly on it.
        self.assertEqual("0px", result["after"]["top"])
        self.assertEqual(0, result["after"]["scrollTop"])
        self.assertIn("cap-0", result["firstText"])
        self.assertIn("post-138", result["lastText"])

        # The frame after the jump leaves the pane exactly where the jump put it.
        self.assertTrue(result["settled"]["sameRow"])
        self.assertEqual(0, result["settled"]["scrollTop"])
        self.assertEqual(2, result["settled"]["spacers"])
        self.assertEqual(239, result["settled"]["counted"])

    def test_jump_rewindows_to_a_capture_below_the_detached_slice(self):
        result = run_ui_scenario(
            JUMP_CAPTURE_BELOW
            + SCROLL_TO
            + JUMP_BY_SPINE_INDEX
            + """
  scrollTo(0);
  const before = { ...paneState("slot0"), firstText: linux.children[1].textContent };
  const jump = jumpTo(0);
  const rows = linux.children;
  return {
    before,
    jump,
    after: paneState("slot0"),
    firstText: rows[1].textContent,
    lastText: rows[rows.length - 2].textContent,
  };
"""
        )

        # The operator is parked at the top of retention; the capture is 600 entries below.
        self.assertEqual(2, result["before"]["spacers"])
        self.assertEqual(0, result["before"]["scrollTop"])
        self.assertIn("pre-0", result["before"]["firstText"])

        self.assertIn("jump-hit", result["jump"]["node"])
        self.assertIn("cap-0", result["jump"]["slot0Row"])
        self.assertIn("cap-top", result["jump"]["rowClass"].split(" "))

        self.assertEqual(2, result["after"]["spacers"])
        self.assertEqual(242, result["after"]["children"])
        self.assertEqual(239, result["after"]["counted"])
        # 120 entries of buffer above the target and 119 below it.
        self.assertIn("pre-480", result["firstText"])
        self.assertIn("post-18", result["lastText"])
        self.assertEqual(10800, result["after"]["scrollTop"])

    def test_jump_lands_on_the_first_line_budget_trimming_left(self):
        result = run_ui_scenario(
            """
  document.getElementById("live-depth-500").dispatch("click");
  const linux = term("slot0");
  send({ type: "exec", phase: "start", id: 9, target: "linux", cmd: "dmesg" });
  for (let index = 0; index < 300; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `cap-${index}` });
  }
  send({
    type: "exec", phase: "end", id: 9, target: "linux",
    ended_by: "idle", ms: 12, bytes: 300, truncated: false, ok: true,
  });
  for (let index = 0; index < 400; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `filler-${index}` });
  }
  flushFrames();
  linux.clientHeight = 400;
  linux.scrollHeight = 9018;
"""
            + JUMP_BY_SPINE_INDEX
            + """
  const jump = jumpTo(0);
  return {
    jump,
    after: paneState("slot0"),
    firstText: linux.children[1].textContent,
    retained: paneModelSpies[0].countedSize(),
    text: linux.textContent,
  };
"""
        )

        # Budget 500 took cap-0 through cap-199, so cap-200 is the capture's top now.
        self.assertEqual(500, result["retained"])
        self.assertIn("jump-hit", result["jump"]["node"])
        self.assertIn("cap-200", result["jump"]["slot0Row"])
        self.assertIn("cap-top", result["jump"]["rowClass"].split(" "))
        self.assertIn("cap-200", result["firstText"])
        self.assertNotIn("cap-199", result["text"])
        self.assertEqual(2, result["after"]["spacers"])
        self.assertEqual(239, result["after"]["counted"])
        self.assertEqual(0, result["after"]["scrollTop"])

    def test_jump_misses_without_changing_the_pill_when_no_line_is_retained(self):
        result = run_ui_scenario(
            """
  document.getElementById("live-depth-500").dispatch("click");
  const linux = term("slot0");
  send({ type: "exec", phase: "start", id: 9, target: "linux", cmd: "one-liner" });
  send({ type: "line", target: "linux", direction: "<<<", text: "capture-line-0" });
  for (let index = 0; index < 500; index += 1) {
    send({ type: "line", target: "linux", direction: "---", text: `filler-${index}` });
  }
  send({
    type: "exec", phase: "end", id: 9, target: "linux",
    ended_by: "idle", ms: 5, bytes: 14, truncated: false, ok: true,
  });
  send({ type: "exec", phase: "start", id: 3, target: "linux", cmd: "pending" });
  flushFrames();
  linux.clientHeight = 400;
  linux.scrollHeight = 9018;
"""
            + JUMP_BY_SPINE_INDEX
            + """
  const pillBefore = document.getElementById("status-pill").textContent;
  const running = jumpTo(0);
  const footOnly = jumpTo(1);
  const stillFollowing = paneState("slot0");
  const retainedFeet = paneModelSpies[0]
    .slice(0, paneModelSpies[0].size())
    .filter((entry) => entry.kind === "foot").length;
  for (let index = 0; index < 600; index += 1) {
    send({ type: "line", target: "linux", direction: "---", text: `later-${index}` });
  }
  flushFrames();
  const gone = jumpTo(1);
  return {
    running,
    footOnly,
    stillFollowing,
    gone,
    retainedFeet,
    pillBefore,
    pill: document.getElementById("status-pill").textContent,
  };
"""
        )

        # Running with nothing captured yet.
        self.assertIn("jump-miss", result["running"]["node"])
        # Sealed, but the one line it captured was trimmed before the seal arrived, so
        # retention holds a footer with nothing under it.
        self.assertIn("jump-miss", result["footOnly"]["node"])
        self.assertEqual(1, result["retainedFeet"])
        # A miss must not detach Follow or open a history window.
        self.assertEqual(0, result["stillFollowing"]["spacers"])
        self.assertEqual(0, result["running"]["slot0Flashes"])
        self.assertEqual(0, result["footOnly"]["slot0Flashes"])
        # Trimming later takes the orphaned seal too.
        self.assertIn("jump-miss", result["gone"]["node"])
        self.assertEqual(result["pillBefore"], result["pill"])

    def test_overlapping_exec_ids_flash_only_the_clicked_target(self):
        result = run_ui_scenario(
            """
  await nextTurn();
  send({ type: "exec", phase: "start", id: 5, target: "linux", cmd: "a" });
  for (let index = 0; index < 40; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `cap-linux-${index}` });
  }
  send({
    type: "exec", phase: "end", id: 5, target: "linux",
    ended_by: "idle", ms: 5, bytes: 40, truncated: false, ok: true,
  });
  send({ type: "exec", phase: "start", id: 5, target: "rtos", cmd: "b" });
  for (let index = 0; index < 40; index += 1) {
    send({ type: "line", target: "rtos", direction: "<<<", text: `cap-rtos-${index}` });
  }
  send({
    type: "exec", phase: "end", id: 5, target: "rtos",
    ended_by: "idle", ms: 5, bytes: 40, truncated: false, ok: true,
  });
  flushFrames();
  await socket.onopen();
"""
            + JUMP_BY_SPINE_INDEX
            + """
  const rtosJump = jumpTo(0);
  const linuxJump = jumpTo(1);
  return {
    rtosJump,
    linuxJump,
    slot0: paneState("slot0"),
    slot1: paneState("slot1"),
  };
""",
            agent_log_entries=[
                {
                    "id": 5,
                    "phase": "end",
                    "target": "rtos",
                    "cmd": "b",
                    "ts": "10:00:01.000",
                    "ended_by": "idle",
                    "ms": 5,
                    "bytes": 40,
                    "truncated": False,
                    "ok": True,
                },
                {
                    "id": 5,
                    "phase": "end",
                    "target": "linux",
                    "cmd": "a",
                    "ts": "10:00:00.000",
                    "ended_by": "idle",
                    "ms": 5,
                    "bytes": 40,
                    "truncated": False,
                    "ok": True,
                },
            ],
        )

        # Both captures are small enough to stay materialized, so both jumps are the
        # immediate path and neither pane may detach.
        self.assertIn("jump-hit", result["rtosJump"]["node"])
        self.assertEqual(0, result["rtosJump"]["slot0Flashes"])
        self.assertIn("cap-rtos-0", result["rtosJump"]["slot1Row"])
        self.assertIn("jump-hit", result["linuxJump"]["node"])
        self.assertEqual(0, result["linuxJump"]["slot1Flashes"])
        self.assertIn("cap-linux-0", result["linuxJump"]["slot0Row"])
        self.assertEqual(0, result["slot0"]["spacers"])
        self.assertEqual(0, result["slot1"]["spacers"])

    def test_overlapping_exec_id_jumps_into_its_own_targets_history(self):
        result = run_ui_scenario(
            """
  await nextTurn();
  const linux = term("slot0");
  send({ type: "exec", phase: "start", id: 5, target: "linux", cmd: "a" });
  for (let index = 0; index < 100; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `cap-linux-${index}` });
  }
  send({
    type: "exec", phase: "end", id: 5, target: "linux",
    ended_by: "idle", ms: 5, bytes: 100, truncated: false, ok: true,
  });
  for (let index = 0; index < 600; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `post-${index}` });
  }
  send({ type: "exec", phase: "start", id: 5, target: "rtos", cmd: "b" });
  for (let index = 0; index < 40; index += 1) {
    send({ type: "line", target: "rtos", direction: "<<<", text: `cap-rtos-${index}` });
  }
  send({
    type: "exec", phase: "end", id: 5, target: "rtos",
    ended_by: "idle", ms: 5, bytes: 40, truncated: false, ok: true,
  });
  flushFrames();
  linux.clientHeight = 400;
  linux.scrollHeight = 12618;
  await socket.onopen();
"""
            + JUMP_BY_SPINE_INDEX
            + """
  const linuxJump = jumpTo(1);
  return { linuxJump, slot0: paneState("slot0"), slot1: paneState("slot1") };
""",
            agent_log_entries=[
                {
                    "id": 5,
                    "phase": "end",
                    "target": "rtos",
                    "cmd": "b",
                    "ts": "10:00:01.000",
                    "ended_by": "idle",
                    "ms": 5,
                    "bytes": 40,
                    "truncated": False,
                    "ok": True,
                },
                {
                    "id": 5,
                    "phase": "end",
                    "target": "linux",
                    "cmd": "a",
                    "ts": "10:00:00.000",
                    "ended_by": "idle",
                    "ms": 5,
                    "bytes": 100,
                    "truncated": False,
                    "ok": True,
                },
            ],
        )

        # The other pane is showing a materialized capture under the same number, which
        # is exactly what a target-blind lookup would jump to.
        self.assertIn("jump-hit", result["linuxJump"]["node"])
        self.assertEqual(0, result["linuxJump"]["slot1Flashes"])
        self.assertIn("cap-linux-0", result["linuxJump"]["slot0Row"])
        self.assertEqual(2, result["slot0"]["spacers"])
        self.assertEqual(0, result["slot1"]["spacers"])

    def test_jump_follows_a_capture_reordered_by_recovery(self):
        result = run_ui_scenario(
            MEASURED_ROWS
            + DETACH_SPANNING_CAPTURE
            + SCROLL_TO
            + CAPTURE_SHAPE
            + JUMP_BY_SPINE_INDEX
            + """
  scrollTo(3600);
  scrollTo(15500);
  bufferAndSeal(40);
  reattach();
  for (let index = 0; index < 300; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `later-${index}` });
  }
  flushFrames();
  linux.scrollHeight = 22212;
  const evicted = {
    capRows: linux.children.filter((c) => c.classList.contains("capture-row")).length,
    spacers: linux.children.filter((c) => c.className === "transcript-spacer").length,
  };
  const jumped = jumpTo(0);
  return { evicted, jump: jumped, shape: shape(), after: paneState("slot0") };
"""
        )

        # The followed window has moved past the whole recovered run.
        self.assertEqual(0, result["evicted"]["capRows"])
        self.assertEqual(0, result["evicted"]["spacers"])

        self.assertIn("jump-hit", result["jump"]["node"])
        self.assertIn("cap-0", result["jump"]["slot0Row"])
        self.assertIn("cap-top", result["jump"]["rowClass"].split(" "))
        # Recovery moved the capture below its Gap, and the jump uses that position
        # rather than where the capture originally arrived.
        self.assertEqual(1, result["shape"]["gaps"])
        self.assertLess(result["shape"]["gapAt"], result["shape"]["topAt"])
        self.assertEqual(2, result["after"]["spacers"])
        self.assertEqual(240, result["after"]["counted"])
        self.assertEqual(14418, result["after"]["scrollTop"])

    def test_a_line_arriving_after_a_history_jump_leaves_the_viewport_alone(self):
        result = run_ui_scenario(
            JUMP_CAPTURE_ABOVE
            + JUMP_BY_SPINE_INDEX
            + """
  jumpTo(0);
  const jumped = paneState("slot0");
  send({ type: "line", target: "linux", direction: "<<<", text: "after-jump" });
  flushFrames();
  const held = { ...paneState("slot0"), text: linux.textContent };
  linux.scrollTop = linux.scrollHeight;
  linux.dispatch("scroll");
  flushFrames();
  const rows = linux.children;
  return {
    jumped,
    held,
    reattached: paneState("slot0"),
    lastText: rows[rows.length - 1].textContent,
    firstText: rows[0].textContent,
  };
"""
        )

        self.assertEqual(2, result["jumped"]["spacers"])
        self.assertEqual(0, result["jumped"]["scrollTop"])

        # Detached means detached: the line is omitted and the pane does not move.
        self.assertEqual(0, result["held"]["scrollTop"])
        self.assertEqual(2, result["held"]["spacers"])
        self.assertNotIn("after-jump", result["held"]["text"])

        # Reaching the true virtual bottom hands the pane back to Follow exactly once,
        # with nothing evicted, so no Gap.
        self.assertEqual(0, result["reattached"]["spacers"])
        self.assertEqual(0, result["reattached"]["gaps"])
        self.assertEqual(240, result["reattached"]["counted"])
        self.assertIn("after-jump", result["lastText"])
        self.assertIn("post-361", result["firstText"])

    def test_a_near_tail_jump_stays_detached_until_the_operator_returns_to_bottom(self):
        result = run_ui_scenario(
            JUMP_CAPTURE_NEAR_TAIL
            + JUMP_BY_SPINE_INDEX
            + """
  const before = paneState("slot0");
  const jump = jumpTo(0);
  const flashed = flashesIn("slot0")[0];
  // The browser answers the jump's own scroll assignment with a scroll event. The target
  // sits inside the last viewport, so this is exactly where a plain tail check reattaches
  // a pane the operator deliberately sent into history.
  linux.dispatch("scroll");
  flushFrames();
  const rows = linux.children;
  const settled = {
    ...paneState("slot0"),
    sameRow: flashesIn("slot0")[0] === flashed,
    firstText: rows[1].textContent,
    lastText: rows[rows.length - 2].textContent,
  };
  send({ type: "line", target: "linux", direction: "<<<", text: "after-jump" });
  flushFrames();
  const held = { ...paneState("slot0"), text: linux.textContent };
  linux.scrollTop = 9000;
  linux.dispatch("scroll");
  flushFrames();
  const away = paneState("slot0");
  linux.scrollTop = linux.scrollHeight;
  linux.dispatch("scroll");
  flushFrames();
  // A second event at the same place must not recover a second time.
  linux.dispatch("scroll");
  flushFrames();
  const settledRows = linux.children;
  return {
    before,
    jump,
    settled,
    held,
    away,
    reattached: paneState("slot0"),
    lastText: settledRows[settledRows.length - 1].textContent,
    replays: (linux.textContent.match(/after-jump/g) || []).length,
  };
"""
        )

        # Detached, and parked far enough from the bottom that nothing here is a tail read.
        self.assertEqual(2, result["before"]["spacers"])
        self.assertEqual(14050, result["before"]["scrollTop"])

        self.assertIn("jump-hit", result["jump"]["node"])
        self.assertIn("cap-0", result["jump"]["slot0Row"])
        self.assertIn("cap-top", result["jump"]["rowClass"].split(" "))

        # The jump's own scroll event leaves the pane detached on the row it flashed.
        self.assertEqual(2, result["settled"]["spacers"])
        self.assertEqual(17874, result["settled"]["scrollTop"])
        self.assertTrue(result["settled"]["sameRow"])
        self.assertEqual(0, result["settled"]["gaps"])
        self.assertEqual(242, result["settled"]["children"])
        self.assertIn("pre-776", result["settled"]["firstText"])
        self.assertIn("post-1", result["settled"]["lastText"])

        # The slice already reaches the model tail, and a detached pane still omits.
        self.assertEqual(17874, result["held"]["scrollTop"])
        self.assertEqual(2, result["held"]["spacers"])
        self.assertNotIn("after-jump", result["held"]["text"])

        # A genuine operator scroll is never swallowed, in either direction.
        self.assertEqual(2, result["away"]["spacers"])
        self.assertEqual(9000, result["away"]["scrollTop"])
        self.assertEqual(0, result["reattached"]["spacers"])
        self.assertEqual(0, result["reattached"]["gaps"])
        self.assertEqual(240, result["reattached"]["counted"])
        self.assertIn("after-jump", result["lastText"])
        self.assertEqual(1, result["replays"])

    def test_the_retained_capture_lookup_is_paid_only_on_a_click(self):
        result = run_ui_scenario(
            JUMP_CAPTURE_ABOVE
            + SCROLL_TO
            + JUMP_BY_SPINE_INDEX
            + """
  const appends = paneReads.captureRange;
  scrollTo(6000);
  scrollTo(3000);
  scrollTo(0);
  const scrolls = paneReads.captureRange;
  const first = jumpTo(0);
  const oneClick = paneReads.captureRange;
  const second = jumpTo(0);
  return {
    appends,
    scrolls,
    oneClick,
    twoClicks: paneReads.captureRange,
    first,
    second,
    after: paneState("slot0"),
  };
"""
        )

        # Streaming 701 entries and dragging the detached window across them never asks
        # the model where a capture is; only the click does, once per click.
        self.assertEqual(0, result["appends"])
        self.assertEqual(0, result["scrolls"])
        self.assertEqual(1, result["oneClick"])
        self.assertEqual(2, result["twoClicks"])

        # The operator is parked on the top of retention, so the capture's first line is
        # already materialized and the jump stays on the immediate path.
        self.assertIn("cap-0", result["first"]["slot0Row"])
        self.assertIn("cap-0", result["second"]["slot0Row"])
        self.assertEqual(2, result["after"]["spacers"])
        self.assertEqual(0, result["after"]["scrollTop"])
        self.assertEqual("0px", result["after"]["top"])

    def test_a_second_jump_clears_the_first_flash_and_its_row(self):
        result = run_ui_scenario(
            """
  const linux = term("slot0");
  send({ type: "exec", phase: "start", id: 7, target: "linux", cmd: "first" });
  for (let index = 0; index < 100; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `cap-a-${index}` });
  }
  send({
    type: "exec", phase: "end", id: 7, target: "linux",
    ended_by: "idle", ms: 12, bytes: 100, truncated: false, ok: true,
  });
  for (let index = 0; index < 400; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `mid-${index}` });
  }
  send({ type: "exec", phase: "start", id: 8, target: "linux", cmd: "second" });
  for (let index = 0; index < 100; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `cap-b-${index}` });
  }
  send({
    type: "exec", phase: "end", id: 8, target: "linux",
    ended_by: "idle", ms: 12, bytes: 100, truncated: false, ok: true,
  });
  for (let index = 0; index < 400; index += 1) {
    send({ type: "line", target: "linux", direction: "<<<", text: `post-${index}` });
  }
  flushFrames();
  linux.clientHeight = 400;
  linux.scrollHeight = 18036;
"""
            + JUMP_BY_SPINE_INDEX
            + """
  const body = document.getElementById("spine-body");
  const firstJump = jumpTo(1);
  const firstRow = flashesIn("slot0")[0];
  const secondJump = jumpTo(0);
  return {
    firstJump,
    secondJump,
    firstRowText: firstRow.textContent,
    firstRowClass: firstRow.className,
    firstRowAttached: firstRow.parentNode !== null,
    nodeClasses: body.children.map((child) => child.className),
    after: paneState("slot0"),
  };
"""
        )

        self.assertIn("cap-a-0", result["firstJump"]["slot0Row"])
        self.assertIn("cap-b-0", result["secondJump"]["slot0Row"])
        # Exactly one flash survives, and the row the first jump used is neither still
        # marked nor still in the pane.
        self.assertEqual(1, result["secondJump"]["slot0Flashes"])
        self.assertIn("cap-a-0", result["firstRowText"])
        self.assertNotIn("jump-flash", result["firstRowClass"].split(" "))
        self.assertFalse(result["firstRowAttached"])
        # The hit marker moves with the click, and the older node keeps neither marker.
        self.assertIn("jump-hit", result["nodeClasses"][0])
        self.assertNotIn("jump-hit", result["nodeClasses"][1])
        self.assertNotIn("jump-miss", result["nodeClasses"][1])
        self.assertEqual(2, result["after"]["spacers"])


if __name__ == "__main__":
    unittest.main()
