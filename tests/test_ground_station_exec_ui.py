import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "static" / "app.js"


def run_ui_scenario(scenario: str, agent_log_entries=None):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not available")
    agent_log_entries = agent_log_entries or []
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

class FakeElement {{
  constructor(id = "") {{
    this.id = id;
    this.children = [];
    this.dataset = {{}};
    this.className = "";
    this.classList = new FakeClassList(this);
    this.title = "";
    this.value = "";
    this.disabled = false;
    this.hidden = false;
    this.scrollTop = 0;
    this.scrolledIntoView = false;
    this.parentNode = null;
    this._textContent = "";
    this.listeners = {{}};
  }}
  get textContent() {{
    return this._textContent + this.children.map((child) => child.textContent || "").join("");
  }}
  set textContent(value) {{
    this._textContent = String(value);
    this.children = [];
  }}
  set innerHTML(value) {{
    this.textContent = value;
  }}
  get childElementCount() {{
    return this.children.length;
  }}
  get firstElementChild() {{
    return this.children[0] || null;
  }}
  get scrollHeight() {{
    return this.children.length;
  }}
  appendChild(child) {{
    if (child && typeof child === "object") child.parentNode = this;
    this.children.push(child);
    return child;
  }}
  append(...children) {{
    children.forEach((child) => this.appendChild(child));
  }}
  removeChild(child) {{
    this.children.splice(this.children.indexOf(child), 1);
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
  getAttribute() {{
    return "0";
  }}
  scrollIntoView() {{
    this.scrolledIntoView = true;
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
  createElement() {{
    return new FakeElement();
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
globalThis.localStorage = {{ getItem: () => null, setItem: () => {{}} }};
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

eval(fs.readFileSync({json.dumps(str(APP_JS))}, "utf8"));
const send = (message) => socket.onmessage({{ data: JSON.stringify(message) }});
const term = (slot) => document.getElementById(`term-${{slot}}`);
const holder = (slot) => document.getElementById(`holder-${{slot}}`);
const nextTurn = () => new Promise((resolve) => setImmediate(resolve));
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
  return {
    spineClasses: body.children.map((child) => child.className),
    tally: document.getElementById("spine-tally").textContent,
    termClasses: term("slot0").children.map((child) => child.className),
    captureClasses: term("slot0").children[1].children.map((child) => child.className),
  };
"""
        )

        self.assertEqual(["spine-node exec sealed"], result["spineClasses"])
        self.assertIn("send 0", result["tally"])
        self.assertEqual(["ln agent", "capture sealed"], result["termClasses"])
        self.assertEqual(["ln dev", "cap-foot"], result["captureClasses"])

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
  const capture = term("slot0").children[1];
  return {
    holderText: holder("slot0").textContent,
    holderClass: holder("slot0").className,
    termClasses: term("slot0").children.map((child) => child.className),
    captureClasses: capture ? capture.children.map((child) => child.className) : [],
    captureText: capture ? capture.textContent : "",
  };
"""
        )

        self.assertEqual("IDLE", result["holderText"])
        self.assertEqual("holder idle", result["holderClass"])
        self.assertEqual(["ln agent", "capture sealed", "ln op"], result["termClasses"])
        self.assertEqual(["ln dev", "cap-foot"], result["captureClasses"])
        self.assertIn("device output", result["captureText"])
        self.assertIn("1.24 s", result["captureText"])
        self.assertIn("3.1 KiB", result["captureText"])
        self.assertIn("closed on idle", result["captureText"])
        self.assertIn("capped", result["captureText"])

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
  const capture = term("slot0").children[0];
  return {
    termChildren: term("slot0").children.length,
    captureRows: capture.children.length,
    text: capture.textContent,
  };
"""
        )

        self.assertEqual(1, result["termChildren"])
        self.assertEqual(75000, result["captureRows"])
        self.assertNotIn("line-0", result["text"])
        self.assertIn("line-75009", result["text"])

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
  execNode.dispatch("click");
  return {
    title: execNode.title,
    className: execNode.className,
    scrolled: !!capture.scrolledIntoView,
    captureClass: capture.className,
    pill: document.getElementById("status-pill").textContent,
  };
"""
        )

        self.assertEqual("Jump to capture", result["title"])
        self.assertIn("exec", result["className"])
        self.assertTrue(result["scrolled"])
        self.assertIn("jump-flash", result["captureClass"])
        self.assertNotIn("not in view", result["pill"])

    def test_trace_jump_missing_anchor_shows_not_in_view(self):
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
  const execNode = document.getElementById("spine-body").children[0];
  execNode.dispatch("click");
  return {
    pill: document.getElementById("status-pill").textContent,
    pillClass: document.getElementById("status-pill").className,
  };
"""
        )

        self.assertEqual("not in view", result["pill"])
        self.assertIn("warn", result["pillClass"])

    def test_trace_jump_running_without_output_is_not_in_view(self):
        result = run_ui_scenario(
            """
  await nextTurn();
  send({
    type: "exec", phase: "start", id: 3, target: "linux",
    cmd: "pending", ts: "10:00:00.000",
  });
  const execNode = document.getElementById("spine-body").children[0];
  execNode.dispatch("click");
  return {
    termChildren: term("slot0").children.length,
    pill: document.getElementById("status-pill").textContent,
  };
"""
        )

        self.assertEqual(0, result["termChildren"])
        self.assertEqual("not in view", result["pill"])

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


if __name__ == "__main__":
    unittest.main()
