import json
import shutil
import subprocess
import unittest
from pathlib import Path

import serial_bridge.app as app_module

ROOT = Path(__file__).resolve().parents[1]
JS_PATH = ROOT / "static" / "ansi_render.js"


def run_ansi_render(expr: str):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not available")
    script = f"""
const fs = require("fs");
eval(fs.readFileSync({json.dumps(str(JS_PATH))}, "utf8"));
const AR = globalThis.AnsiRender;
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


class AnsiRenderModuleTest(unittest.TestCase):
    def test_base_style_is_plain(self):
        style = run_ansi_render("AR.baseStyle()")
        self.assertEqual(
            {
                "fg": None,
                "bg": None,
                "bold": False,
                "dim": False,
                "underline": False,
                "inverse": False,
            },
            style,
        )

    def test_apply_sgr_basic_foreground_and_reset(self):
        red = run_ansi_render('AR.applySgr(AR.baseStyle(), "31")')
        self.assertEqual("var(--ansi-1)", red["fg"])
        reset = run_ansi_render('AR.applySgr(AR.applySgr(AR.baseStyle(), "31"), "0")')
        self.assertEqual(run_ansi_render("AR.baseStyle()"), reset)

    def test_apply_sgr_bright_foreground(self):
        style = run_ansi_render('AR.applySgr(AR.baseStyle(), "91")')
        self.assertEqual("var(--ansi-9)", style["fg"])

    def test_apply_sgr_bold_and_background(self):
        style = run_ansi_render('AR.applySgr(AR.baseStyle(), "1;42")')
        self.assertTrue(style["bold"])
        self.assertEqual("var(--ansi-2)", style["bg"])

    def test_indexed_color_palette_and_cube(self):
        self.assertEqual("var(--ansi-1)", run_ansi_render("AR.indexedColor(1)"))
        self.assertEqual("rgb(215, 0, 0)", run_ansi_render("AR.indexedColor(160)"))

    def test_parse_segments_applies_sgr_and_joins_plain_text(self):
        segments = run_ansi_render(
            r'AR.parseSegments("\x1b[31mred\x1b[0m plain")'
        )
        self.assertEqual(
            [
                {"text": "red", "style": {"fg": "var(--ansi-1)", "bg": None, "bold": False, "dim": False, "underline": False, "inverse": False}},
                {"text": " plain", "style": {"fg": None, "bg": None, "bold": False, "dim": False, "underline": False, "inverse": False}},
            ],
            segments,
        )

    def test_parse_segments_discards_non_sgr_sequences(self):
        segments = run_ansi_render(
            r'AR.parseSegments("\x1b[2K\x1b[31mok")'
        )
        self.assertEqual(1, len(segments))
        self.assertEqual("ok", segments[0]["text"])
        self.assertEqual("var(--ansi-1)", segments[0]["style"]["fg"])

    def test_parse_segments_truecolor_foreground(self):
        segments = run_ansi_render(
            r'AR.parseSegments("\x1b[38;2;255;128;64mhi")'
        )
        self.assertEqual("hi", segments[0]["text"])
        self.assertEqual("rgb(255, 128, 64)", segments[0]["style"]["fg"])


class AnsiRenderUiWiringTest(unittest.TestCase):
    def test_index_loads_ansi_render_before_app(self):
        html = (app_module.STATIC / "index.html").read_text(encoding="utf-8")
        ansi_pos = html.index("/static/ansi_render.js")
        app_pos = html.index("/static/app.js")
        self.assertLess(ansi_pos, app_pos)

    def test_app_wires_render_ansi(self):
        app_js = (app_module.STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn("AnsiRender", app_js)
        self.assertIn("renderAnsi", app_js)
        self.assertNotIn("function applySgr", app_js)


if __name__ == "__main__":
    unittest.main()
