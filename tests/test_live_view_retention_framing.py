import re
import unittest
from pathlib import Path

import serial_bridge.app as app_module

ROOT = Path(__file__).resolve().parents[1]
CONTEXT_PATH = ROOT / "CONTEXT.md"
INDEX_PATH = app_module.STATIC / "index.html"

LIVE_DEPTH_BUTTON_IDS = ("live-depth-500", "live-depth-5000", "live-depth-75000")
LIVE_DEPTH_VISIBLE_LABELS = {
    "live-depth-500": "retain 500",
    "live-depth-5000": "5k",
    "live-depth-75000": "75k",
}


def _glossary_entry(text: str, term: str) -> str:
    pattern = rf"\*\*{re.escape(term)}\*\*:(.*?)(?=\n\*\*|\Z)"
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        raise AssertionError(f"missing glossary entry for {term!r}")
    return match.group(1)


def _button_markup(html: str, button_id: str) -> str:
    match = re.search(
        rf'<button[^>]*\bid="{re.escape(button_id)}"[^>]*>.*?</button>',
        html,
        re.DOTALL,
    )
    if not match:
        raise AssertionError(f"missing live-depth button {button_id!r}")
    return match.group(0)


def _button_accessible_name(markup: str) -> str:
    for attribute in ("aria-label", "title"):
        match = re.search(rf'{attribute}="([^"]+)"', markup)
        if match:
            return match.group(1)
    return ""


class LiveViewRetentionLabelsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = INDEX_PATH.read_text(encoding="utf-8")

    def test_live_depth_group_uses_retained_transcript_depth_label(self):
        match = re.search(
            r'<div class="live-depth" role="group" aria-label="([^"]+)"',
            self.html,
        )
        self.assertIsNotNone(match)
        self.assertEqual("Retained transcript depth", match.group(1))

    def test_live_depth_buttons_use_retention_visible_labels(self):
        for button_id, visible_label in LIVE_DEPTH_VISIBLE_LABELS.items():
            with self.subTest(button_id=button_id):
                markup = _button_markup(self.html, button_id)
                self.assertIn(f">{visible_label}<", markup)

    def test_each_live_depth_stop_names_retained_entries_per_pane(self):
        for button_id in LIVE_DEPTH_BUTTON_IDS:
            with self.subTest(button_id=button_id):
                accessible_name = _button_accessible_name(
                    _button_markup(self.html, button_id)
                )
                lowered = accessible_name.lower()
                self.assertIn("retain", lowered)
                self.assertIn("per pane", lowered)
                self.assertRegex(lowered, r"entries|entry")


class ContextRetentionFramingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = CONTEXT_PATH.read_text(encoding="utf-8")

    def test_live_view_budget_describes_retained_transcript_entries(self):
        entry = _glossary_entry(self.context, "Live View Budget")
        lowered = entry.lower()
        self.assertIn("retained transcript entries", lowered)
        self.assertIn("virtual history", lowered)
        self.assertNotIn("current view may materialize", lowered)
        self.assertNotIn("materialized rows", lowered)

    def test_live_view_budget_separates_dom_materialization(self):
        entry = _glossary_entry(self.context, "Live View Budget")
        lowered = entry.lower()
        self.assertIn("dom materialization", lowered)
        self.assertIn("virtual window", lowered)
        self.assertNotIn("240", entry)

    def test_live_view_budget_avoids_buffer_and_scrollback_framing(self):
        entry = _glossary_entry(self.context, "Live View Budget")
        lowered = entry.lower()
        self.assertIn("complete session log", lowered)
        definition, avoid = entry.split("_Avoid_:", 1)
        self.assertNotIn("buffer size", definition.lower())
        self.assertNotIn("scrollback", definition.lower())
        self.assertIn("buffer size", avoid.lower())
        self.assertIn("scrollback", avoid.lower())

    def test_trace_jump_succeeds_while_any_capture_line_remains_retained(self):
        entry = _glossary_entry(self.context, "Trace Jump")
        lowered = entry.lower()
        self.assertNotIn("current view", lowered)
        self.assertIn("materialize", lowered)
        self.assertIn("retained", lowered)
        self.assertIn("misses only after all capture lines leave retention", lowered)


if __name__ == "__main__":
    unittest.main()
