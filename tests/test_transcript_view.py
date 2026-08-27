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

    def test_trim_keeps_a_foot_when_a_matching_line_still_remains(self):
        # A foot can arrive before its own lines: a capture can seal while a pane is
        # detached (feet always materialize), and its captured lines only reappear later,
        # via replay, once the pane re-attaches and the omitted lines are recovered
        # (Follow/Trace Jump territory, exercised in app.js, not here). Those replayed
        # lines slot in above the seal, so the seal ends up closing its run rather than
        # leading it, and trimming one of them still leaves the seal a line to close.
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
        self.assertEqual(["line", "foot", "line"], kinds)

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


class TranscriptViewWindowHelpersTest(unittest.TestCase):
    def test_size_counts_every_retained_entry_including_feet(self):
        size = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(500);
              pane.appendLine({ direction: "<<<", text: "a", who: "dev", tstamp: "", captureId: 1 });
              pane.appendFoot({ captureId: 1, text: "sealed" });
              pane.appendGap(4);
              return pane.size();
            })()
            """
        )
        self.assertEqual(3, size)

    def test_size_follows_budget_trimming(self):
        result = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(3);
              for (let i = 0; i < 50; i++) {
                pane.appendLine({ direction: ">>>", text: String(i), who: "you", tstamp: "" });
              }
              return { size: pane.size(), counted: pane.countedSize() };
            })()
            """
        )
        self.assertEqual(3, result["size"])
        self.assertEqual(3, result["counted"])

    def test_slice_returns_the_requested_index_range_oldest_first(self):
        texts = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(500);
              for (let i = 0; i < 10; i++) {
                pane.appendLine({ direction: ">>>", text: `t${i}`, who: "you", tstamp: "" });
              }
              return pane.slice(3, 6).map((e) => e.text);
            })()
            """
        )
        self.assertEqual(["t3", "t4", "t5"], texts)

    def test_slice_indexes_from_the_oldest_surviving_entry_after_trimming(self):
        texts = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(5);
              for (let i = 0; i < 20; i++) {
                pane.appendLine({ direction: ">>>", text: `t${i}`, who: "you", tstamp: "" });
              }
              return pane.slice(0, 2).map((e) => e.text);
            })()
            """
        )
        self.assertEqual(["t15", "t16"], texts)

    def test_slice_clamps_out_of_range_bounds(self):
        result = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(500);
              for (let i = 0; i < 4; i++) {
                pane.appendLine({ direction: ">>>", text: `t${i}`, who: "you", tstamp: "" });
              }
              return {
                past: pane.slice(2, 99).map((e) => e.text),
                before: pane.slice(-5, 2).map((e) => e.text),
                empty: pane.slice(3, 1),
              };
            })()
            """
        )
        self.assertEqual(["t2", "t3"], result["past"])
        self.assertEqual(["t0", "t1"], result["before"])
        self.assertEqual([], result["empty"])

    def test_slice_returns_a_copy_not_the_live_list(self):
        length = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(500);
              pane.appendLine({ direction: ">>>", text: "a", who: "you", tstamp: "" });
              pane.slice(0, 1).push({ kind: "line" });
              return pane.size();
            })()
            """
        )
        self.assertEqual(1, length)


class TranscriptViewHeightIndexTest(unittest.TestCase):
    def test_every_entry_starts_at_the_estimated_height(self):
        result = run_transcript_view(
            """
            (() => {
              const index = TV.createHeightIndex(10, 18);
              return { total: index.total(), first: index.offsetOf(0), fifth: index.offsetOf(5) };
            })()
            """
        )
        self.assertEqual(180, result["total"])
        self.assertEqual(0, result["first"])
        self.assertEqual(90, result["fifth"])

    def test_a_measured_height_shifts_every_later_offset_and_the_total(self):
        result = run_transcript_view(
            """
            (() => {
              const index = TV.createHeightIndex(10, 18);
              index.setHeight(2, 54);
              return {
                before: index.offsetOf(2),
                after: index.offsetOf(3),
                total: index.total(),
                heightAt: index.heightAt(2),
              };
            })()
            """
        )
        self.assertEqual(36, result["before"])
        self.assertEqual(90, result["after"])
        self.assertEqual(216, result["total"])
        self.assertEqual(54, result["heightAt"])

    def test_index_at_offset_finds_the_entry_covering_a_pixel(self):
        result = run_transcript_view(
            """
            (() => {
              const index = TV.createHeightIndex(10, 18);
              index.setHeight(2, 54);
              return {
                zero: index.indexAtOffset(0),
                inside: index.indexAtOffset(20),
                boundary: index.indexAtOffset(36),
                inTall: index.indexAtOffset(80),
                afterTall: index.indexAtOffset(90),
              };
            })()
            """
        )
        self.assertEqual(0, result["zero"])
        self.assertEqual(1, result["inside"])
        self.assertEqual(2, result["boundary"])
        self.assertEqual(2, result["inTall"])
        self.assertEqual(3, result["afterTall"])

    def test_index_at_offset_clamps_outside_the_retained_range(self):
        result = run_transcript_view(
            """
            (() => {
              const index = TV.createHeightIndex(4, 18);
              return { below: index.indexAtOffset(-500), above: index.indexAtOffset(99999) };
            })()
            """
        )
        self.assertEqual(0, result["below"])
        self.assertEqual(3, result["above"])

    def test_unusable_measurements_leave_the_index_untouched(self):
        result = run_transcript_view(
            """
            (() => {
              const index = TV.createHeightIndex(4, 18);
              index.setHeight(1, 0);
              index.setHeight(1, -20);
              index.setHeight(1, Infinity);
              index.setHeight(1, NaN);
              index.setHeight(99, 40);
              index.setHeight(-1, 40);
              return { total: index.total(), heightAt: index.heightAt(1) };
            })()
            """
        )
        self.assertEqual(72, result["total"])
        self.assertEqual(18, result["heightAt"])

    def test_an_empty_index_reports_finite_non_negative_zero(self):
        result = run_transcript_view(
            """
            (() => {
              const index = TV.createHeightIndex(0, 18);
              return { total: index.total(), offset: index.offsetOf(0), at: index.indexAtOffset(50) };
            })()
            """
        )
        self.assertEqual(0, result["total"])
        self.assertEqual(0, result["offset"])
        self.assertEqual(0, result["at"])

    def test_offsets_stay_exact_across_a_large_retained_depth(self):
        result = run_transcript_view(
            """
            (() => {
              const index = TV.createHeightIndex(75000, 18);
              index.setHeight(40000, 36);
              return {
                total: index.total(),
                before: index.offsetOf(40000),
                after: index.offsetOf(40001),
                at: index.indexAtOffset(index.offsetOf(60000)),
              };
            })()
            """
        )
        self.assertEqual(75000 * 18 + 18, result["total"])
        self.assertEqual(40000 * 18, result["before"])
        self.assertEqual(40000 * 18 + 36, result["after"])
        self.assertEqual(60000, result["at"])

    def test_growing_keeps_measured_heights_and_estimates_the_new_entries(self):
        result = run_transcript_view(
            """
            (() => {
              const index = TV.createHeightIndex(4, 18);
              index.setHeight(1, 50);
              index.grow(6);
              return {
                size: index.size(),
                total: index.total(),
                measured: index.heightAt(1),
                appended: index.heightAt(5),
                offsetPastOld: index.offsetOf(4),
                covering: index.indexAtOffset(120),
                last: index.indexAtOffset(99999),
              };
            })()
            """
        )
        self.assertEqual(6, result["size"])
        # 18 + 50 + 18 + 18 + 18 + 18: the one measured height survived the growth.
        self.assertEqual(140, result["total"])
        self.assertEqual(50, result["measured"])
        self.assertEqual(18, result["appended"])
        self.assertEqual(104, result["offsetPastOld"])
        self.assertEqual(4, result["covering"])
        self.assertEqual(5, result["last"])

    def test_growing_to_the_same_or_a_smaller_count_leaves_the_index_untouched(self):
        result = run_transcript_view(
            """
            (() => {
              const index = TV.createHeightIndex(4, 18);
              index.setHeight(0, 40);
              index.grow(4);
              index.grow(2);
              index.grow(-7);
              return { size: index.size(), total: index.total(), first: index.heightAt(0) };
            })()
            """
        )
        self.assertEqual(4, result["size"])
        self.assertEqual(94, result["total"])
        self.assertEqual(40, result["first"])


class TranscriptViewCaptureOrderTest(unittest.TestCase):
    """The retained model is the sole authority on visual order, so recovery reordering
    and post-seal replay insertion are model operations rather than renderer special
    cases."""

    def test_moving_a_capture_puts_its_lines_and_foot_after_a_trailing_gap(self):
        result = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(500);
              pane.appendLine({ direction: "<<<", text: "before", tstamp: "t0" });
              pane.appendLine({ direction: "<<<", text: "cap-0", tstamp: "t1", captureId: 7 });
              pane.appendLine({ direction: "<<<", text: "cap-1", tstamp: "t2", captureId: 7 });
              pane.appendLine({ direction: "<<<", text: "cap-2", tstamp: "t3", captureId: 7 });
              pane.appendFoot({ captureId: 7, text: "sealed" });
              pane.appendGap(8);
              const before = pane.countedSize();
              pane.moveCaptureToEnd(7);
              return {
                before,
                counted: pane.countedSize(),
                size: pane.size(),
                shape: pane.entries().map((e) => e.kind + ":" + (e.text || e.count)),
              };
            })()
            """
        )
        # Four lines and the Gap count; the seal does not, and the reorder changes neither.
        self.assertEqual(5, result["before"])
        self.assertEqual(5, result["counted"])
        self.assertEqual(6, result["size"])
        # Canonical visual order: the Gap, then the whole capture run in its original
        # relative order, then the seal that closes it.
        self.assertEqual(
            [
                "line:before",
                "gap:8",
                "line:cap-0",
                "line:cap-1",
                "line:cap-2",
                "foot:sealed",
            ],
            result["shape"],
        )

    def test_moving_a_capture_carries_only_the_lines_still_retained(self):
        result = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(4);
              pane.appendLine({ direction: "<<<", text: "cap-0", captureId: 7 });
              pane.appendLine({ direction: "<<<", text: "cap-1", captureId: 7 });
              pane.appendLine({ direction: "<<<", text: "cap-2", captureId: 7 });
              pane.appendFoot({ captureId: 7, text: "sealed" });
              pane.appendLine({ direction: "<<<", text: "after-0" });
              pane.appendLine({ direction: "<<<", text: "after-1" });
              pane.appendGap(3);
              const trimmed = pane.entries().map((e) => e.kind + ":" + (e.text || e.count));
              pane.moveCaptureToEnd(7);
              return {
                trimmed,
                counted: pane.countedSize(),
                shape: pane.entries().map((e) => e.kind + ":" + (e.text || e.count)),
              };
            })()
            """
        )
        # Budget 4 evicted the two oldest capture lines but kept the foot, since one of
        # the lines it seals is still retained.
        self.assertEqual(
            ["line:cap-2", "foot:sealed", "line:after-0", "line:after-1", "gap:3"],
            result["trimmed"],
        )
        self.assertEqual(4, result["counted"])
        self.assertEqual(
            ["line:after-0", "line:after-1", "gap:3", "line:cap-2", "foot:sealed"],
            result["shape"],
        )

    def test_moving_a_capture_that_is_no_longer_retained_changes_nothing(self):
        result = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(500);
              pane.appendLine({ direction: "<<<", text: "a" });
              pane.appendLine({ direction: "<<<", text: "b" });
              pane.moveCaptureToEnd(7);
              pane.moveCaptureToEnd(null);
              return {
                counted: pane.countedSize(),
                shape: pane.entries().map((e) => e.kind + ":" + e.text),
              };
            })()
            """
        )
        self.assertEqual(2, result["counted"])
        self.assertEqual(["line:a", "line:b"], result["shape"])

    def test_a_captured_line_lands_before_its_seal_once_the_capture_has_a_foot(self):
        result = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(500);
              pane.appendLine({ direction: "<<<", text: "cap-0", captureId: 7 });
              pane.appendFoot({ captureId: 7, text: "sealed" });
              pane.appendLine({ direction: "<<<", text: "replay-0", captureId: 7 });
              pane.appendLine({ direction: "<<<", text: "replay-1", captureId: 7 });
              return {
                counted: pane.countedSize(),
                shape: pane.entries().map((e) => e.kind + ":" + e.text),
              };
            })()
            """
        )
        self.assertEqual(3, result["counted"])
        self.assertEqual(
            ["line:cap-0", "line:replay-0", "line:replay-1", "foot:sealed"],
            result["shape"],
        )

    def test_lines_outside_a_sealed_capture_still_append_at_the_tail(self):
        result = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(500);
              pane.appendLine({ direction: "<<<", text: "running-0", captureId: 7 });
              pane.appendLine({ direction: "<<<", text: "running-1", captureId: 7 });
              pane.appendFoot({ captureId: 7, text: "sealed-7" });
              pane.appendLine({ direction: "<<<", text: "plain" });
              pane.appendLine({ direction: "<<<", text: "other", captureId: 9 });
              return pane.entries().map((e) => e.kind + ":" + e.text);
            })()
            """
        )
        # A running capture has no seal to sit before, and neither a plain line nor a
        # different capture may be pulled inside capture 7's box.
        self.assertEqual(
            [
                "line:running-0",
                "line:running-1",
                "foot:sealed-7",
                "line:plain",
                "line:other",
            ],
            result,
        )

    def test_replay_insertion_and_reorder_keep_budget_trimming_honest(self):
        result = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(5);
              pane.appendLine({ direction: "<<<", text: "old-0" });
              pane.appendLine({ direction: "<<<", text: "old-1" });
              pane.appendLine({ direction: "<<<", text: "cap-0", captureId: 7 });
              pane.appendFoot({ captureId: 7, text: "sealed" });
              pane.appendGap(2);
              pane.moveCaptureToEnd(7);
              const moved = pane.entries().map((e) => e.kind + ":" + (e.text || e.count));
              pane.appendLine({ direction: "<<<", text: "replay-0", captureId: 7 });
              pane.appendLine({ direction: "<<<", text: "replay-1", captureId: 7 });
              return {
                moved,
                counted: pane.countedSize(),
                size: pane.size(),
                shape: pane.entries().map((e) => e.kind + ":" + (e.text || e.count)),
              };
            })()
            """
        )
        self.assertEqual(
            ["line:old-0", "line:old-1", "gap:2", "line:cap-0", "foot:sealed"],
            result["moved"],
        )
        # Two replayed lines take the count to 6 over a budget of 5, so the oldest
        # counted entry goes, and the seal keeps trailing its own run.
        self.assertEqual(5, result["counted"])
        self.assertEqual(6, result["size"])
        self.assertEqual(
            [
                "line:old-1",
                "gap:2",
                "line:cap-0",
                "line:replay-0",
                "line:replay-1",
                "foot:sealed",
            ],
            result["shape"],
        )

    def test_a_seal_trimmed_out_of_retention_stops_capturing_later_lines(self):
        result = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(2);
              pane.appendLine({ direction: "<<<", text: "cap-0", captureId: 7 });
              pane.appendFoot({ captureId: 7, text: "sealed" });
              pane.appendLine({ direction: "<<<", text: "a" });
              pane.appendLine({ direction: "<<<", text: "b" });
              const dropped = pane.entries().map((e) => e.kind + ":" + e.text);
              pane.appendLine({ direction: "<<<", text: "replay-0", captureId: 7 });
              return {
                dropped,
                counted: pane.countedSize(),
                shape: pane.entries().map((e) => e.kind + ":" + e.text),
              };
            })()
            """
        )
        # Once the capture's last line goes, its orphaned seal goes too, so a later
        # captured line has nothing to sit before and simply appends.
        self.assertEqual(["line:a", "line:b"], result["dropped"])
        self.assertEqual(2, result["counted"])
        self.assertEqual(["line:b", "line:replay-0"], result["shape"])


class TranscriptViewCaptureContiguityTest(unittest.TestCase):
    """A capture's retained entries are one unbroken run, wherever its lines arrive in the
    stream. Anything that barged in mid-capture sits below the whole run, which is where
    the pane has always drawn it."""

    def test_a_captured_line_rejoins_its_run_below_an_interleaved_system_row(self):
        result = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(500);
              pane.appendLine({ direction: "<<<", text: "cap-0", captureId: 7 });
              pane.appendLine({ direction: "---", text: "note" });
              pane.appendLine({ direction: "<<<", text: "cap-1", captureId: 7 });
              pane.appendLine({ direction: ">>>", text: "typed" });
              pane.appendLine({ direction: "<<<", text: "cap-2", captureId: 7 });
              return {
                counted: pane.countedSize(),
                shape: pane.entries().map((e) => e.direction + ":" + e.text),
              };
            })()
            """
        )
        self.assertEqual(5, result["counted"])
        self.assertEqual(
            ["<<<:cap-0", "<<<:cap-1", "<<<:cap-2", "---:note", ">>>:typed"],
            result["shape"],
        )

    def test_a_seal_lands_on_its_run_rather_than_below_an_interleaved_write(self):
        result = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(500);
              pane.appendLine({ direction: "<<<", text: "cap-0", captureId: 7 });
              pane.appendLine({ direction: ">>>", text: "typed" });
              pane.appendFoot({ captureId: 7, text: "sealed" });
              return pane.entries().map((e) => e.kind + ":" + e.text);
            })()
            """
        )
        self.assertEqual(
            ["line:cap-0", "foot:sealed", "line:typed"], result
        )

    def test_sealing_twice_does_not_leave_two_feet_for_one_capture(self):
        result = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(500);
              pane.appendLine({ direction: "<<<", text: "cap-0", captureId: 7 });
              pane.appendFoot({ captureId: 7, text: "sealed" });
              pane.appendFoot({ captureId: 7, text: "sealed again" });
              return pane.entries().map((e) => e.kind + ":" + e.text);
            })()
            """
        )
        self.assertEqual(["line:cap-0", "foot:sealed"], result)

    def test_two_interleaved_captures_each_keep_their_own_run(self):
        result = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(500);
              pane.appendLine({ direction: "<<<", text: "a-0", captureId: 7 });
              pane.appendLine({ direction: "<<<", text: "b-0", captureId: 9 });
              pane.appendLine({ direction: "<<<", text: "a-1", captureId: 7 });
              pane.appendLine({ direction: "<<<", text: "b-1", captureId: 9 });
              pane.appendFoot({ captureId: 7, text: "sealed-a" });
              pane.appendLine({ direction: "<<<", text: "b-2", captureId: 9 });
              return pane.entries().map((e) => e.kind + ":" + e.text);
            })()
            """
        )
        # Capture 9's run must not be pulled into capture 7's, and sealing 7 must not
        # close anything belonging to 9.
        self.assertEqual(
            [
                "line:a-0",
                "line:a-1",
                "foot:sealed-a",
                "line:b-0",
                "line:b-1",
                "line:b-2",
            ],
            result,
        )

    def test_a_capture_with_nothing_retained_starts_a_fresh_run_at_the_tail(self):
        result = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(2);
              pane.appendLine({ direction: "<<<", text: "cap-0", captureId: 7 });
              pane.appendLine({ direction: "---", text: "note-0" });
              pane.appendLine({ direction: "---", text: "note-1" });
              const trimmed = pane.entries().map((e) => e.text);
              pane.appendLine({ direction: "<<<", text: "cap-1", captureId: 7 });
              return { trimmed, shape: pane.entries().map((e) => e.text) };
            })()
            """
        )
        # Budget took capture 7's only line, so there is no run left to rejoin and the
        # next captured line simply starts one at the tail.
        self.assertEqual(["note-0", "note-1"], result["trimmed"])
        self.assertEqual(["note-1", "cap-1"], result["shape"])

    def test_interleaving_keeps_the_budget_and_the_count_honest(self):
        result = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(4);
              pane.appendLine({ direction: "<<<", text: "cap-0", captureId: 7 });
              pane.appendLine({ direction: "---", text: "note" });
              pane.appendLine({ direction: "<<<", text: "cap-1", captureId: 7 });
              pane.appendGap(6);
              pane.appendLine({ direction: "<<<", text: "cap-2", captureId: 7 });
              return {
                counted: pane.countedSize(),
                size: pane.size(),
                shape: pane.entries().map((e) => e.kind + ":" + (e.text || e.count)),
              };
            })()
            """
        )
        # Five counted entries against a budget of four: the oldest goes, which is the
        # capture's own first line, and the run stays whole around what remains.
        self.assertEqual(4, result["counted"])
        self.assertEqual(4, result["size"])
        self.assertEqual(
            ["line:cap-1", "line:cap-2", "line:note", "gap:6"],
            result["shape"],
        )

    def test_appending_to_a_run_already_at_the_tail_never_splices(self):
        result = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(100000);
              const real = Array.prototype.splice;
              let splices = 0;
              Array.prototype.splice = function (...args) {
                splices += 1;
                return real.apply(this, args);
              };
              try {
                for (let i = 0; i < 2000; i += 1) {
                  pane.appendLine({ direction: "<<<", text: `plain-${i}` });
                }
                const afterPlain = splices;
                for (let i = 0; i < 2000; i += 1) {
                  pane.appendLine({ direction: "<<<", text: `cap-${i}`, captureId: 7 });
                }
                const afterRun = splices;
                pane.appendFoot({ captureId: 7, text: "sealed" });
                const afterFoot = splices;
                pane.appendLine({ direction: "<<<", text: "replay", captureId: 7 });
                const afterReplay = splices;
                pane.appendLine({ direction: "---", text: "note" });
                pane.appendLine({ direction: "<<<", text: "rejoin", captureId: 7 });
                return {
                  afterPlain,
                  afterRun,
                  afterFoot,
                  afterReplay,
                  afterInterleave: splices,
                };
              } finally {
                Array.prototype.splice = real;
              }
            })()
            """
        )
        # The hot paths — plain lines, a running capture's own lines, and its seal — all
        # land at the tail, so none of them may walk or rewrite retention.
        self.assertEqual(0, result["afterPlain"])
        self.assertEqual(0, result["afterRun"])
        self.assertEqual(0, result["afterFoot"])
        # A replayed line goes in just above a seal that is itself at the tail, which is a
        # single splice and still no scan.
        self.assertEqual(1, result["afterReplay"])
        # Only genuine interleaving pays to find the run again.
        self.assertEqual(2, result["afterInterleave"])


class TranscriptViewCaptureRangeTest(unittest.TestCase):
    """Trace Jump has to find a capture the renderer has not materialized, so retention
    answers where that capture currently sits in visual order."""

    def test_capture_range_reports_the_first_line_and_last_entry_positions(self):
        result = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(500);
              pane.appendLine({ direction: "<<<", text: "before" });
              pane.appendLine({ direction: "<<<", text: "cap-0", captureId: 7 });
              pane.appendLine({ direction: "<<<", text: "cap-1", captureId: 7 });
              pane.appendFoot({ captureId: 7, text: "sealed" });
              pane.appendLine({ direction: "<<<", text: "after" });
              return { range: pane.captureRange(7), size: pane.size() };
            })()
            """
        )
        self.assertEqual({"first": 1, "last": 3}, result["range"])
        self.assertEqual(5, result["size"])

    def test_capture_range_indexes_the_same_entries_slice_returns(self):
        texts = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(500);
              for (let i = 0; i < 4; i += 1) {
                pane.appendLine({ direction: "<<<", text: `pre-${i}` });
              }
              for (let i = 0; i < 3; i += 1) {
                pane.appendLine({ direction: "<<<", text: `cap-${i}`, captureId: 7 });
              }
              pane.appendFoot({ captureId: 7, text: "sealed" });
              const range = pane.captureRange(7);
              return pane.slice(range.first, range.last + 1).map((e) => e.text);
            })()
            """
        )
        self.assertEqual(["cap-0", "cap-1", "cap-2", "sealed"], texts)

    def test_capture_range_follows_trimming_of_the_oldest_capture_lines(self):
        result = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(3);
              for (let i = 0; i < 3; i += 1) {
                pane.appendLine({ direction: "<<<", text: `cap-${i}`, captureId: 7 });
              }
              pane.appendFoot({ captureId: 7, text: "sealed" });
              pane.appendLine({ direction: "<<<", text: "after-0" });
              pane.appendLine({ direction: "<<<", text: "after-1" });
              const range = pane.captureRange(7);
              return { range, first: pane.slice(range.first, range.first + 1)[0].text };
            })()
            """
        )
        self.assertEqual({"first": 0, "last": 1}, result["range"])
        self.assertEqual("cap-2", result["first"])

    def test_capture_range_is_null_when_only_the_seal_is_retained(self):
        # Trimming took the capture's single line before the seal arrived, so retention
        # holds a footer with nothing under it. There is no line to jump to.
        result = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(2);
              pane.appendLine({ direction: "<<<", text: "cap-0", captureId: 7 });
              pane.appendLine({ direction: "<<<", text: "after-0" });
              pane.appendLine({ direction: "<<<", text: "after-1" });
              pane.appendFoot({ captureId: 7, text: "sealed" });
              return {
                range: pane.captureRange(7),
                shape: pane.entries().map((e) => e.kind + ":" + e.text),
              };
            })()
            """
        )
        self.assertIsNone(result["range"])
        self.assertEqual(
            ["line:after-0", "line:after-1", "foot:sealed"],
            result["shape"],
        )

    def test_capture_range_is_null_for_a_capture_the_pane_never_held(self):
        result = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(500);
              pane.appendLine({ direction: "<<<", text: "a" });
              pane.appendLine({ direction: "<<<", text: "cap-0", captureId: 7 });
              return [pane.captureRange(9), pane.captureRange(null)];
            })()
            """
        )
        self.assertEqual([None, None], result)

    def test_capture_range_follows_a_recovery_reorder(self):
        result = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(500);
              pane.appendLine({ direction: "<<<", text: "cap-0", captureId: 7 });
              pane.appendLine({ direction: "<<<", text: "cap-1", captureId: 7 });
              pane.appendFoot({ captureId: 7, text: "sealed" });
              const before = pane.captureRange(7);
              pane.appendGap(8);
              pane.moveCaptureToEnd(7);
              const after = pane.captureRange(7);
              return { before, after, first: pane.slice(after.first, after.first + 1)[0].text };
            })()
            """
        )
        self.assertEqual({"first": 0, "last": 2}, result["before"])
        # The Gap took the top, so the capture's run now starts below it.
        self.assertEqual({"first": 1, "last": 3}, result["after"])
        self.assertEqual("cap-0", result["first"])

    def test_capture_range_returns_positions_rather_than_the_retained_entries(self):
        # A caller must not be handed anything it can mutate the model through.
        result = run_transcript_view(
            """
            (() => {
              const pane = TV.createPane(500);
              pane.appendLine({ direction: "<<<", text: "cap-0", captureId: 7 });
              const range = pane.captureRange(7);
              range.first = 99;
              return {
                keys: Object.keys(range).sort(),
                types: Object.values(pane.captureRange(7)).map((v) => typeof v),
                stable: pane.captureRange(7),
              };
            })()
            """
        )
        self.assertEqual(["first", "last"], result["keys"])
        self.assertEqual(["number", "number"], result["types"])
        self.assertEqual({"first": 0, "last": 0}, result["stable"])


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
