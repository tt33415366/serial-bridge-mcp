import unittest

from serial_bridge.hub.readiness import ShellReadiness


class ShellReadinessTest(unittest.TestCase):
    def test_unknown_without_prompt_or_observation(self):
        tracker = ShellReadiness()
        self.assertEqual(("unknown", None), tracker.evaluate("linux", r"# $"))
        tracker.observe("linux", "root@dev:~# ", "t1")
        self.assertEqual(("unknown", None), tracker.evaluate("linux", None))

    def test_ready_when_last_line_matches_prompt(self):
        tracker = ShellReadiness()
        tracker.observe("linux", "output\r\nroot@dev:~# ", "t1")
        self.assertEqual(("ready", "t1"), tracker.evaluate("linux", r"# $"))

    def test_trailing_newline_after_prompt_is_not_ready(self):
        tracker = ShellReadiness()
        tracker.observe("linux", "root@dev:~# \r\n", "t1")
        self.assertEqual(("unknown", None), tracker.evaluate("linux", r"# $"))

    def test_later_output_replaces_the_evidence(self):
        tracker = ShellReadiness()
        tracker.observe("linux", "root@dev:~# ", "t1")
        tracker.observe("linux", "kernel: oops", "t2")
        self.assertEqual(("unknown", None), tracker.evaluate("linux", r"# $"))

    def test_clear_drops_old_readiness(self):
        tracker = ShellReadiness()
        tracker.observe("linux", "root@dev:~# ", "t1")
        tracker.clear("linux")
        self.assertEqual(("unknown", None), tracker.evaluate("linux", r"# $"))

    def test_ansi_is_stripped_before_matching(self):
        tracker = ShellReadiness()
        tracker.observe("linux", "\x1b[32mroot\x1b[0m# ", "t1")
        self.assertEqual(("ready", "t1"), tracker.evaluate("linux", r"root# $"))

    def test_targets_are_independent(self):
        tracker = ShellReadiness()
        tracker.observe("linux", "# ", "t1")
        tracker.clear("rtos")
        self.assertEqual("ready", tracker.evaluate("linux", r"# $")[0])
