import json
import shutil
import subprocess
import unittest
from pathlib import Path

import serial_bridge.app as app_module

ROOT = Path(__file__).resolve().parents[1]
JS_PATH = ROOT / "static" / "command_history.js"


def run_command_history(expr: str):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not available")
    script = f"""
const fs = require("fs");
eval(fs.readFileSync({json.dumps(str(JS_PATH))}, "utf8"));
const CH = globalThis.CommandHistory;
const result = {expr};
console.log(JSON.stringify(result));
"""
    completed = subprocess.run(
        [node, "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout.strip())


class CommandHistoryModuleTest(unittest.TestCase):
    def test_storage_key_uses_target_slot(self):
        key = run_command_history('CH.storageKey("slot0")')
        self.assertEqual("serial-bridge.command-history.slot0", key)

    def test_record_trims_and_skips_blank(self):
        history = run_command_history('CH.recordCommand([], "  ls\\n")')
        self.assertEqual(["ls"], history)
        unchanged = run_command_history('CH.recordCommand(["ls"], "   ")')
        self.assertEqual(["ls"], unchanged)

    def test_record_suppresses_consecutive_duplicates(self):
        history = run_command_history(
            'CH.recordCommand(CH.recordCommand([], "make"), "make")'
        )
        self.assertEqual(["make"], history)

    def test_record_caps_at_two_thousand(self):
        history = run_command_history(
            """
            Array.from({ length: 2001 }, (_, index) => `cmd-${index}`)
              .reduce((acc, cmd) => CH.recordCommand(acc, cmd), [])
            """
        )
        self.assertEqual(2000, len(history))
        self.assertEqual("cmd-1", history[0])
        self.assertEqual("cmd-2000", history[-1])

    def test_matches_for_prefix_is_case_sensitive_newest_first(self):
        matches = run_command_history(
            """
            CH.matchesForPrefix(
              ["make clean", "ls", "make linux", "Make"],
              "make"
            )
            """
        )
        self.assertEqual(["make linux", "make clean"], matches)

    def test_empty_prefix_returns_full_history_newest_first(self):
        matches = run_command_history('CH.matchesForPrefix(["a", "b", "c"], "")')
        self.assertEqual(["c", "b", "a"], matches)

    def test_browser_empty_up_walks_newest_first_and_down_restores_draft(self):
        result = run_command_history(
            """
            (() => {
              const browser = CH.createBrowser(["pwd", "ls", "make"]);
              const up1 = browser.arrowUp("");
              const up2 = browser.arrowUp(up1.value);
              const up3 = browser.arrowUp(up2.value);
              const down1 = browser.arrowDown(up3.value);
              const down2 = browser.arrowDown(down1.value);
              const down3 = browser.arrowDown(down2.value);
              return {
                up: [up1.value, up2.value, up3.value],
                down: [down1.value, down2.value, down3.value],
              };
            })()
            """
        )
        self.assertEqual(["make", "ls", "pwd"], result["up"])
        self.assertEqual(["ls", "make", ""], result["down"])

    def test_browser_prefix_up_finds_newest_startswith_match(self):
        result = run_command_history(
            """
            (() => {
              const browser = CH.createBrowser(["make clean", "ls", "make linux"]);
              const up1 = browser.arrowUp("make");
              const up2 = browser.arrowUp(up1.value);
              const up3 = browser.arrowUp(up2.value);
              const down1 = browser.arrowDown(up3.value);
              const down2 = browser.arrowDown(down1.value);
              const down3 = browser.arrowDown(down2.value);
              return {
                up: [up1.value, up2.value, up3.value],
                down: [down1.value, down2.value, down3.value],
              };
            })()
            """
        )
        self.assertEqual(["make linux", "make clean", "make clean"], result["up"])
        self.assertEqual(["make linux", "make", "make"], result["down"])

    def test_load_and_save_history_round_trip(self):
        payload = run_command_history(
            """
            (() => {
              const storage = {
                data: {},
                getItem(key) { return this.data[key] ?? null; },
                setItem(key, value) { this.data[key] = value; },
              };
              const slot = "slot1";
              const history = CH.recordCommand([], "echo hi");
              CH.saveHistory(storage, slot, history);
              return {
                key: CH.storageKey(slot),
                loaded: CH.loadHistory(storage, slot),
              };
            })()
            """
        )
        self.assertEqual("serial-bridge.command-history.slot1", payload["key"])
        self.assertEqual(["echo hi"], payload["loaded"])


class CommandHistoryUiWiringTest(unittest.TestCase):
    def test_index_loads_command_history_before_app(self):
        html = (app_module.STATIC / "index.html").read_text(encoding="utf-8")
        history_pos = html.index("/static/command_history.js")
        app_pos = html.index("/static/app.js")
        self.assertLess(history_pos, app_pos)

    def test_app_wires_composer_history_keys(self):
        app_js = (app_module.STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn("CommandHistory", app_js)
        self.assertIn("ArrowUp", app_js)
        self.assertIn("ArrowDown", app_js)
        self.assertIn("setSelectionRange", app_js)
        self.assertIn("recordCommand", app_js)


if __name__ == "__main__":
    unittest.main()
