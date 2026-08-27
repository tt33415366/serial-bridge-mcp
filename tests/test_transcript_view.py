import json
import shutil
import subprocess
import unittest
from pathlib import Path

import serial_bridge.app as app_module

ROOT = Path(__file__).resolve().parents[1]
JS_PATH = ROOT / "static" / "transcript_view.js"


def run_transcript_view(expr: str):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not available")
    script = f"""
const fs = require("fs");
eval(fs.readFileSync({json.dumps(str(JS_PATH))}, "utf8"));
const TV = globalThis.TranscriptView;
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


class TranscriptViewModuleTest(unittest.TestCase):
    def test_append_line_defaults_capture_id_to_null(self):
        entries = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(500);
              pane.appendLine({ direction: ">>>", text: "hi", who: "you", tstamp: "t1" });
              return pane.entries();
            })()
            """
        )
        self.assertEqual(
            [{"kind": "line", "direction": ">>>", "text": "hi", "who": "you", "tstamp": "t1", "captureId": None}],
            entries,
        )

    def test_append_line_records_capture_id_when_captured(self):
        entries = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(500);
              pane.appendLine({ direction: "<<<", text: "line", who: "dev", tstamp: "t1", captureId: 7 });
              return pane.entries();
            })()
            """
        )
        self.assertEqual(7, entries[0]["captureId"])

    def test_consecutive_gaps_merge_into_one(self):
        result = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(500);
              pane.appendGap(3);
              pane.appendGap(4);
              return { entries: pane.entries(), counted: pane.countedSize() };
            })()
            """
        )
        self.assertEqual([{"kind": "gap", "count": 7}], result["entries"])
        self.assertEqual(1, result["counted"])

    def test_gap_after_non_gap_pushes_new_entry(self):
        entries = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(500);
              pane.appendLine({ direction: ">>>", text: "a", who: "you", tstamp: "" });
              pane.appendGap(2);
              return pane.entries().map((e) => e.kind);
            })()
            """
        )
        self.assertEqual(["line", "gap"], entries)

    def test_foot_does_not_count_toward_budget(self):
        counted = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(500);
              pane.appendLine({ direction: "<<<", text: "a", who: "dev", tstamp: "", captureId: 1 });
              pane.appendFoot({ captureId: 1, text: "sealed" });
              return pane.countedSize();
            })()
            """
        )
        self.assertEqual(1, counted)

    def test_trim_drops_oldest_counted_entries_to_stay_within_budget(self):
        result = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(2);
              pane.appendLine({ direction: ">>>", text: "1", who: "you", tstamp: "" });
              pane.appendLine({ direction: ">>>", text: "2", who: "you", tstamp: "" });
              pane.appendLine({ direction: ">>>", text: "3", who: "you", tstamp: "" });
              return { entries: pane.entries().map((e) => e.text), counted: pane.countedSize() };
            })()
            """
        )
        self.assertEqual(["2", "3"], result["entries"])
        self.assertEqual(2, result["counted"])

    def test_trim_counts_gap_as_one_entry(self):
        result = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(1);
              pane.appendLine({ direction: ">>>", text: "1", who: "you", tstamp: "" });
              pane.appendGap(50);
              return { entries: pane.entries().map((e) => e.kind), counted: pane.countedSize() };
            })()
            """
        )
        self.assertEqual(["gap"], result["entries"])
        self.assertEqual(1, result["counted"])

    def test_trim_drops_orphaned_leading_foot_once_its_lines_are_gone(self):
        result = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(1);
              pane.appendLine({ direction: "<<<", text: "a", who: "dev", tstamp: "", captureId: 1 });
              pane.appendFoot({ captureId: 1, text: "sealed-1" });
              pane.appendLine({ direction: ">>>", text: "b", who: "you", tstamp: "" });
              return pane.entries();
            })()
            """
        )
        self.assertEqual(
            [{"kind": "line", "direction": ">>>", "text": "b", "who": "you", "tstamp": "", "captureId": None}],
            result,
        )

    def test_trim_keeps_leading_foot_when_a_matching_line_still_remains(self):
        # A foot can dual-write before its own lines: a capture can seal while a pane
        # is detached (feet always materialize), and its captured lines only reappear
        # later, via replay, once the pane re-attaches and the omitted lines are
        # recovered (Follow/Trace Jump territory, exercised in app.js, not here).
        kinds = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(2);
              pane.appendFoot({ captureId: 1, text: "sealed-1" });
              pane.appendLine({ direction: "<<<", text: "a", who: "dev", tstamp: "", captureId: 1 });
              pane.appendLine({ direction: "<<<", text: "b", who: "dev", tstamp: "", captureId: 1 });
              pane.appendLine({ direction: ">>>", text: "c", who: "you", tstamp: "" });
              return pane.entries().map((e) => e.kind);
            })()
            """
        )
        self.assertEqual(["foot", "line", "line"], kinds)

    def test_set_budget_tightens_without_inserting_a_gap(self):
        entries = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(5);
              pane.appendLine({ direction: ">>>", text: "1", who: "you", tstamp: "" });
              pane.appendLine({ direction: ">>>", text: "2", who: "you", tstamp: "" });
              pane.appendLine({ direction: ">>>", text: "3", who: "you", tstamp: "" });
              pane.setBudget(1);
              return pane.entries();
            })()
            """
        )
        self.assertEqual(
            [{"kind": "line", "direction": ">>>", "text": "3", "who": "you", "tstamp": "", "captureId": None}],
            entries,
        )

    def test_clear_empties_the_pane(self):
        result = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(5);
              pane.appendLine({ direction: ">>>", text: "1", who: "you", tstamp: "" });
              pane.appendGap(2);
              pane.clear();
              return { entries: pane.entries(), counted: pane.countedSize() };
            })()
            """
        )
        self.assertEqual([], result["entries"])
        self.assertEqual(0, result["counted"])

    def test_entries_returns_a_copy_not_the_live_list(self):
        result = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(5);
              pane.appendLine({ direction: ">>>", text: "1", who: "you", tstamp: "" });
              const snapshot = pane.entries();
              snapshot.push({ kind: "line", direction: ">>>", text: "mutated", who: "you", tstamp: "", captureId: null });
              return pane.entries().length;
            })()
            """
        )
        self.assertEqual(1, result)

    def test_trim_retains_last_budget_counted_entries_after_many_appends(self):
        result = run_transcript_view(
            """
            (() => {
              const budget = 5;
              const pane = TV.createPane(budget);
              for (let i = 0; i < 500; i++) {
                pane.appendLine({ direction: ">>>", text: String(i), who: "you", tstamp: "" });
              }
              return {
                texts: pane.entries().map((e) => e.text),
                counted: pane.countedSize(),
                length: pane.entries().length,
              };
            })()
            """
        )
        self.assertEqual(["495", "496", "497", "498", "499"], result["texts"])
        self.assertEqual(5, result["counted"])
        self.assertEqual(5, result["length"])

    def test_trim_does_not_splice_on_every_drop_at_cap(self):
        splice_calls = run_transcript_view(
            """
            (() => {
              let spliceCalls = 0;
              const origSplice = Array.prototype.splice;
              Array.prototype.splice = function (...args) {
                spliceCalls += 1;
                return origSplice.apply(this, args);
              };
              try {
                const pane = TV.createPane(3);
                for (let i = 0; i < 1000; i++) {
                  pane.appendLine({ direction: ">>>", text: String(i), who: "you", tstamp: "" });
                }
                return spliceCalls;
              } finally {
                Array.prototype.splice = origSplice;
              }
            })()
            """
        )
        self.assertEqual(0, splice_calls)


class TranscriptViewUiWiringTest(unittest.TestCase):
    def test_index_loads_transcript_view_before_app(self):
        html = (app_module.STATIC / "index.html").read_text(encoding="utf-8")
        transcript_view_pos = html.index("/static/transcript_view.js")
        app_pos = html.index("/static/app.js")
        self.assertLess(transcript_view_pos, app_pos)

    def test_app_wires_transcript_view_panes(self):
        app_js = (app_module.STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn("TranscriptView", app_js)
        self.assertIn("createPane", app_js)
        self.assertIn("appendGap", app_js)
        self.assertIn("appendFoot", app_js)
        self.assertIn("setBudget", app_js)


if __name__ == "__main__":
    unittest.main()
