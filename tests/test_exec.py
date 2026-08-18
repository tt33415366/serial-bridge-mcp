import threading
import unittest
from pathlib import Path

from serial_bridge.config import Config
from serial_bridge.hub import ExecEngine, Hub, PortWorker, TargetQueue


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class ScriptedSerial:
    def __init__(self, clock, chunks=(), on_read=None):
        self.clock = clock
        self.chunks = list(chunks)
        self.on_read = on_read
        self.writes = []

    def write(self, raw):
        self.writes.append(raw)

    def flush(self):
        pass

    def read(self, _size):
        if self.on_read:
            chunk = self.on_read()
            if chunk is not None:
                return chunk
        if self.chunks and self.chunks[0][0] <= self.clock.now:
            return self.chunks.pop(0)[1]
        return b""


def execute(chunks=(), *, prompt=None, prompt_is_regex=False, serial_factory=None):
    clock = FakeClock()
    serial = (
        serial_factory(clock)
        if serial_factory
        else ScriptedSerial(clock, chunks)
    )
    queue = TargetQueue()
    request = queue.enqueue_exec(
        target="linux",
        cmd="show",
        prompt=prompt,
        prompt_is_regex=prompt_is_regex,
    )
    assert queue.next_write() is request
    result = ExecEngine(clock=clock.monotonic, sleep=clock.sleep).execute(
        serial,
        queue,
        request,
        b"\n",
    )
    return result, serial, clock


class ExecEngineTest(unittest.TestCase):
    def test_idle_completion_uses_one_second_gap(self):
        result, serial, clock = execute(
            [(0.0, b"show\r\n"), (0.2, b"answer\r\n")]
        )

        self.assertEqual(b"show\n", serial.writes[0])
        self.assertEqual("show\r\nanswer\r\n", result["output"])
        self.assertFalse(result["timed_out"])
        self.assertFalse(result["aborted"])
        self.assertGreaterEqual(clock.now, 1.2)
        self.assertLess(clock.now, 1.31)

    def test_literal_prompt_completes_before_idle(self):
        result, _serial, clock = execute(
            [(0.2, b"answer\r\ndevice> ")],
            prompt="device> ",
        )

        self.assertTrue(result["ok"])
        self.assertEqual("answer\r\ndevice> ", result["output"])
        self.assertLess(clock.now, 1.0)

    def test_regex_prompt_is_opt_in(self):
        result, _serial, clock = execute(
            [(0.2, b"answer\r\nrtos-17# ")],
            prompt=r"rtos-\d+# $",
            prompt_is_regex=True,
        )

        self.assertTrue(result["ok"])
        self.assertLess(clock.now, 1.0)

    def test_total_timeout_is_sixty_seconds_and_keeps_output(self):
        def serial_factory(clock):
            def read():
                clock.sleep(0.5)
                return b"x"

            return ScriptedSerial(clock, on_read=read)

        result, _serial, clock = execute(serial_factory=serial_factory)

        self.assertFalse(result["ok"])
        self.assertTrue(result["timed_out"])
        self.assertTrue(result["output"])
        self.assertEqual(60.0, clock.now)

    def test_total_timeout_wins_when_prompt_arrives_at_deadline(self):
        def serial_factory(clock):
            def read():
                clock.sleep(60.0)
                return b"device> "

            return ScriptedSerial(clock, on_read=read)

        result, _serial, clock = execute(
            prompt="device> ",
            serial_factory=serial_factory,
        )

        self.assertFalse(result["ok"])
        self.assertTrue(result["timed_out"])
        self.assertEqual("device> ", result["output"])
        self.assertEqual(60.0, clock.now)

    def test_output_is_truncated_to_trailing_32_kib(self):
        prefix = b"a" * 8192
        trailing = b"b" * (32 * 1024 - 4) + b"DONE"
        result, _serial, _clock = execute(
            [(0.0, prefix + trailing)],
            prompt="DONE",
        )

        self.assertTrue(result["truncated"])
        self.assertEqual(32 * 1024, len(result["output"].encode("utf-8")))
        self.assertEqual(trailing.decode(), result["output"])

    def test_prompt_is_detected_before_output_is_truncated(self):
        result, _serial, clock = execute(
            [(0.2, b"READY>" + b"x" * (40 * 1024))],
            prompt="READY>",
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["truncated"])
        self.assertLess(clock.now, 1.0)

    def test_ansi_is_stripped_without_removing_command_echo(self):
        result, _serial, _clock = execute(
            [(0.0, b"\x1b[31mshow\x1b[0m\r\n\x1b[2Kanswer\r\n")],
        )

        self.assertEqual("show\r\nanswer\r\n", result["output"])

    def test_invalid_regex_prompt_is_rejected_before_any_tx(self):
        result, serial, _clock = execute(
            [(0.0, b"answer\r\n")],
            prompt="rtos-[",
            prompt_is_regex=True,
        )

        self.assertFalse(result["ok"])
        self.assertIn("regex", result["error"])
        self.assertEqual([], serial.writes)

    def test_abort_returns_partial_output(self):
        clock = FakeClock()
        queue = TargetQueue()
        request = queue.enqueue_exec("linux", "show")
        self.assertIs(request, queue.next_write())
        sent_partial = False

        def read():
            nonlocal sent_partial
            if not sent_partial:
                sent_partial = True
                return b"partial"
            clock.sleep(0.1)
            if clock.now >= 0.2:
                queue.abort_agents()
            return b""

        serial = ScriptedSerial(clock, on_read=read)

        result = ExecEngine(clock=clock.monotonic, sleep=clock.sleep).execute(
            serial, queue, request, b"\n"
        )

        self.assertFalse(result["ok"])
        self.assertTrue(result["aborted"])
        self.assertEqual("partial", result["output"])


class FakeExecWorker:
    def __init__(self):
        self.is_open = True
        self._stop = threading.Event()
        self.calls = []

    def enqueue_exec(self, cmd, prompt=None, prompt_is_regex=False):
        self.calls.append((cmd, prompt, prompt_is_regex))
        return object()

    def wait_exec(self, _request):
        return {
            "ok": True,
            "target": "linux",
            "output": "done",
            "truncated": False,
            "timed_out": False,
            "aborted": False,
        }


class HubExecTest(unittest.TestCase):
    def make_hub(self):
        config = Config(
            slots=[
                {"name": "linux", "title": "Linux", "com": "COM3", "baud": 115200},
                {"name": "rtos", "title": "RTOS", "com": "COM6", "baud": 115200},
            ],
            path=Path("serial_bridge.json"),
        )
        return Hub(config)

    def test_exec_delegates_to_open_target_with_literal_prompt_default(self):
        hub = self.make_hub()
        worker = FakeExecWorker()
        hub.mode = "bridge"
        hub.workers["linux"] = worker

        result = hub.exec("linux", "show", prompt="device> ")

        self.assertTrue(result["ok"])
        self.assertEqual([("show", "device> ", False)], worker.calls)

    def test_exec_in_crt_mode_fails_with_result_fields(self):
        result = self.make_hub().exec("linux", "show")

        self.assertEqual(
            {
                "ok": False,
                "target": "linux",
                "output": "",
                "truncated": False,
                "timed_out": False,
                "aborted": False,
                "error": "CRT Mode is active; switch to Bridge Mode before Exec",
            },
            result,
        )

    def test_stop_bridge_cannot_miss_concurrent_exec_enqueue(self):
        hub = self.make_hub()
        worker = PortWorker("linux", "COM3", 115200, hub)
        worker.is_open = True
        hub.mode = "bridge"
        hub.workers["linux"] = worker
        enqueue_entered = threading.Event()
        release_enqueue = threading.Event()
        original_enqueue = worker._tx.enqueue_exec

        def pausing_enqueue(*args, **kwargs):
            enqueue_entered.set()
            release_enqueue.wait(1)
            return original_enqueue(*args, **kwargs)

        worker._tx.enqueue_exec = pausing_enqueue
        result = {}
        exec_thread = threading.Thread(
            target=lambda: result.update(hub.exec("linux", "show")),
            daemon=True,
        )
        stop_thread = threading.Thread(target=hub.stop_bridge)

        exec_thread.start()
        self.assertTrue(enqueue_entered.wait(1))
        stop_thread.start()
        release_enqueue.set()
        stop_thread.join(1)
        exec_thread.join(1)

        self.assertFalse(exec_thread.is_alive())
        self.assertTrue(result["aborted"])


if __name__ == "__main__":
    unittest.main()
