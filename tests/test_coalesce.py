import unittest

from serial_bridge.hub.coalesce import LineCoalescer


class DeferredTimer:
    def __init__(self, _interval, callback):
        self.callback = callback
        self.daemon = False

    def start(self):
        pass

    def cancel(self):
        pass


class LineCoalescerTest(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.coalescer = LineCoalescer(self.sent.append, timer_factory=DeferredTimer)

    def _line(self, text, target="linux"):
        return {
            "type": "line",
            "target": target,
            "direction": "<<<",
            "who": "",
            "text": text,
            "ts": "12:00:00.000",
        }

    def test_consecutive_line_emits_are_not_dispatched_until_flush(self):
        self.coalescer.emit(self._line("one"))
        self.coalescer.emit(self._line("two"))
        self.assertEqual([], self.sent)
        self.coalescer.emit({"type": "exec", "phase": "start", "id": 1, "target": "linux"})

        self.assertEqual("line", self.sent[0]["type"])
        self.assertEqual(["one", "two"], [item["text"] for item in self.sent[0]["items"]])
        self.assertEqual("exec", self.sent[1]["type"])

    def test_single_flushed_line_keeps_legacy_shape(self):
        self.coalescer.emit(self._line("only"))
        self.coalescer.emit({"type": "status", "mode": "bridge"})

        self.assertEqual(
            {
                "type": "line",
                "target": "linux",
                "direction": "<<<",
                "who": "",
                "text": "only",
                "ts": "12:00:00.000",
            },
            self.sent[0],
        )
        self.assertNotIn("items", self.sent[0])


if __name__ == "__main__":
    unittest.main()
