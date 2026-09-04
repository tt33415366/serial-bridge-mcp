import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from serial_bridge.config import Config
from serial_bridge.hub import ExecEngine, ExecSession, Hub, PortWorker, TargetQueue


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


def execute(
    chunks=(),
    *,
    prompt=None,
    prompt_is_regex=False,
    grep=None,
    grep_is_regex=False,
    grep_context=0,
    serial_factory=None,
    on_done=None,
    abort_before_execute=False,
):
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
        grep=grep,
        grep_is_regex=grep_is_regex,
        grep_context=grep_context,
    )
    assert queue.next_write() is request
    if abort_before_execute:
        queue.abort_agents()
    result = ExecEngine(clock=clock.monotonic, sleep=clock.sleep).execute(
        serial,
        queue,
        request,
        b"\n",
        on_done=on_done,
    )
    return result, serial, clock


class RecordingExecHub:
    def __init__(self):
        self.starts = []
        self.ends = []

    def record_exec_start(self, target, cmd, prompt):
        self.starts.append((target, cmd, prompt))
        return 17

    def record_exec_end(
        self, exec_id, target, ended_by, ms, captured_bytes, truncated, ok
    ):
        self.ends.append(
            (exec_id, target, ended_by, ms, captured_bytes, truncated, ok)
        )


class ScriptedExecEngine:
    def __init__(
        self,
        clock,
        *,
        result=None,
        ended_by=None,
        chunks=(),
        elapsed=0.0,
        error=None,
    ):
        self.clock = clock.monotonic
        self._fake_clock = clock
        self._result = result
        self._ended_by = ended_by
        self._chunks = chunks
        self._elapsed = elapsed
        self._error = error

    def execute(self, _serial, _queue, _request, _line_ending, **callbacks):
        for chunk in self._chunks:
            callbacks["on_rx"](chunk)
        self._fake_clock.sleep(self._elapsed)
        if self._error is not None:
            raise self._error
        if self._ended_by is not None:
            callbacks["on_done"](self._ended_by)
        return self._result


def execute_session(
    chunks=(),
    *,
    prompt=None,
    serial_factory=None,
):
    clock = FakeClock()
    serial = (
        serial_factory(clock)
        if serial_factory
        else ScriptedSerial(clock, chunks)
    )
    queue = TargetQueue()
    request = queue.enqueue_exec("linux", "show", prompt=prompt)
    assert queue.next_write() is request
    hub = RecordingExecHub()
    engine = ExecEngine(clock=clock.monotonic, sleep=clock.sleep)

    result = ExecSession(hub, engine).execute(
        serial,
        queue,
        request,
        b"\n",
    )
    return result, hub


class ExecSessionTest(unittest.TestCase):
    def test_idle_result_and_supervision_come_from_session(self):
        result, hub = execute_session(
            [(0.0, b"show\r\n"), (0.2, b"answer\r\n")]
        )

        self.assertTrue(result["ok"])
        self.assertEqual("show\r\nanswer\r\n", result["output"])
        self.assertEqual([("linux", "show", None)], hub.starts)
        self.assertEqual(
            [(17, "linux", "idle", 1200, 14, False, True)],
            hub.ends,
        )

    def test_prompt_result_and_supervision_come_from_session(self):
        result, hub = execute_session(
            [(0.2, b"answer\r\ndevice> ")],
            prompt="device> ",
        )

        self.assertTrue(result["ok"])
        self.assertEqual("answer\r\ndevice> ", result["output"])
        self.assertEqual([("linux", "show", "device> ")], hub.starts)
        self.assertEqual(
            [
                (
                    17,
                    "linux",
                    "prompt",
                    200,
                    len(b"answer\r\ndevice> "),
                    False,
                    True,
                )
            ],
            hub.ends,
        )

    def test_timeout_result_and_supervision_come_from_session(self):
        def serial_factory(clock):
            def read():
                clock.sleep(0.5)
                return b"x"

            return ScriptedSerial(clock, on_read=read)

        result, hub = execute_session(serial_factory=serial_factory)

        self.assertFalse(result["ok"])
        self.assertTrue(result["timed_out"])
        self.assertEqual(
            [(17, "linux", "timeout", 60000, 120, False, False)],
            hub.ends,
        )

    def test_exception_reraises_and_records_error_end(self):
        clock = FakeClock()
        hub = RecordingExecHub()
        engine = ScriptedExecEngine(
            clock,
            chunks=(b"partial",),
            elapsed=0.25,
            error=OSError("flush failed"),
        )
        queue = TargetQueue()
        request = queue.enqueue_exec("linux", "show")
        self.assertIs(request, queue.next_write())

        with self.assertRaisesRegex(OSError, "flush failed"):
            ExecSession(hub, engine).execute(
                ScriptedSerial(clock),
                queue,
                request,
                b"\n",
            )

        self.assertEqual(
            [(17, "linux", "error", 250, len(b"partial"), False, False)],
            hub.ends,
        )

    def test_missing_completion_returns_failure_and_records_error_end(self):
        clock = FakeClock()
        hub = RecordingExecHub()
        engine = ScriptedExecEngine(
            clock,
            result={
                "ok": True,
                "target": "linux",
                "output": "partial",
                "truncated": True,
                "timed_out": False,
                "aborted": False,
            },
            chunks=(b"partial",),
            elapsed=0.5,
        )
        queue = TargetQueue()
        request = queue.enqueue_exec("linux", "show")
        self.assertIs(request, queue.next_write())

        result = ExecSession(hub, engine).execute(
            ScriptedSerial(clock),
            queue,
            request,
            b"\n",
        )

        self.assertEqual("Exec failed", result["error"])
        self.assertEqual(
            [(17, "linux", "error", 500, len(b"partial"), False, False)],
            hub.ends,
        )

    def test_abort_records_raw_bytes_and_result_truncated_flag(self):
        clock = FakeClock()
        hub = RecordingExecHub()
        raw = (b"\x1b[31m" * 7000) + b"DONE"
        engine = ScriptedExecEngine(
            clock,
            result={
                "ok": False,
                "target": "linux",
                "output": "DONE",
                "truncated": False,
                "timed_out": False,
                "aborted": True,
            },
            ended_by="abort",
            chunks=(raw,),
            elapsed=0.4,
        )
        queue = TargetQueue()
        request = queue.enqueue_exec("linux", "show")
        self.assertIs(request, queue.next_write())

        result = ExecSession(hub, engine).execute(
            ScriptedSerial(clock),
            queue,
            request,
            b"\n",
        )

        self.assertTrue(result["aborted"])
        self.assertGreater(len(raw), ExecEngine.OUTPUT_CAP_BYTES)
        self.assertEqual(
            [(17, "linux", "abort", 400, len(raw), False, False)],
            hub.ends,
        )


class ExecEngineTest(unittest.TestCase):
    def test_on_done_reports_idle_once(self):
        calls = []

        result, _serial, _clock = execute(
            [(0.0, b"show\r\n"), (0.2, b"answer\r\n")],
            on_done=calls.append,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(["idle"], calls)

    def test_on_done_reports_prompt_once(self):
        calls = []

        result, _serial, _clock = execute(
            [(0.2, b"answer\r\ndevice> ")],
            prompt="device> ",
            on_done=calls.append,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(["prompt"], calls)

    def test_on_done_reports_timeout_once(self):
        calls = []

        def serial_factory(clock):
            def read():
                clock.sleep(0.5)
                return b"x"

            return ScriptedSerial(clock, on_read=read)

        result, _serial, _clock = execute(
            serial_factory=serial_factory,
            on_done=calls.append,
        )

        self.assertTrue(result["timed_out"])
        self.assertEqual(["timeout"], calls)

    def test_on_done_reports_error_before_write(self):
        calls = []

        result, serial, _clock = execute(
            prompt="rtos-[",
            prompt_is_regex=True,
            on_done=calls.append,
        )

        self.assertFalse(result["ok"])
        self.assertEqual([], serial.writes)
        self.assertEqual(["error"], calls)

    def test_on_done_reports_abort_when_write_is_disallowed(self):
        calls = []

        result, serial, _clock = execute(
            abort_before_execute=True,
            on_done=calls.append,
        )

        self.assertTrue(result["aborted"])
        self.assertEqual([], serial.writes)
        self.assertEqual(["abort"], calls)

    def test_prompt_and_idle_present_the_same_stripped_capture(self):
        chunks = [(0.0, b"show\r\nanswer\r\n")]
        idle, _, _ = execute(chunks)
        prompted, _, _ = execute(chunks, prompt="answer")
        self.assertEqual(idle["output"], prompted["output"])
        self.assertEqual(idle["truncated"], prompted["truncated"])

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

        calls = []
        result = ExecEngine(clock=clock.monotonic, sleep=clock.sleep).execute(
            serial,
            queue,
            request,
            b"\n",
            on_done=calls.append,
        )

        self.assertFalse(result["ok"])
        self.assertTrue(result["aborted"])
        self.assertEqual("partial", result["output"])
        self.assertEqual(["abort"], calls)

    def test_literal_grep_keeps_matching_lines_only(self):
        result, serial, _ = execute(
            [(0.0, b"show\r\nerror 1\r\nok\r\nerror 2\r\n")],
            grep="error",
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["grepped"])
        self.assertEqual(2, result["match_count"])
        self.assertEqual("error 1\r\nerror 2\r\n", result["output"])
        self.assertFalse(result["truncated"])
        self.assertTrue(serial.writes)

    def test_literal_grep_is_case_sensitive(self):
        result, _, _ = execute([(0.0, b"Error\r\nerror\r\n")], grep="error")
        self.assertEqual("error\r\n", result["output"])
        self.assertEqual(1, result["match_count"])

    def test_empty_grep_is_rejected_before_tx(self):
        result, serial, _ = execute([(0.0, b"x\r\n")], grep="")
        self.assertFalse(result["ok"])
        self.assertIn("grep", result["error"].lower())
        self.assertEqual([], serial.writes)
        self.assertNotIn("grepped", result)

    def test_regex_grep_is_opt_in(self):
        result, _, _ = execute(
            [(0.0, b"error 1\r\nfail\r\nerror 2\r\n")],
            grep=r"err.*\d",
            grep_is_regex=True,
        )
        self.assertEqual("error 1\r\nerror 2\r\n", result["output"])
        self.assertEqual(2, result["match_count"])

    def test_regex_grep_without_flag_is_literal(self):
        result, _, _ = execute(
            [(0.0, b"foo.*bar\r\nfoobar\r\n")],
            grep="foo.*bar",
        )
        self.assertEqual("foo.*bar\r\n", result["output"])
        self.assertEqual(1, result["match_count"])

    def test_invalid_regex_grep_is_rejected_before_tx(self):
        result, serial, _ = execute(
            [(0.0, b"x\r\n")],
            grep="err[",
            grep_is_regex=True,
        )
        self.assertFalse(result["ok"])
        self.assertIn("regex", result["error"])
        self.assertEqual([], serial.writes)
        self.assertNotIn("grepped", result)

    def test_zero_hits_returns_empty_output(self):
        result, _, _ = execute([(0.0, b"show\r\nanswer\r\n")], grep="error")
        self.assertTrue(result["ok"])
        self.assertEqual("", result["output"])
        self.assertEqual(0, result["match_count"])
        self.assertTrue(result["grepped"])

    def test_omitting_grep_keeps_today_result_keys(self):
        result, _, _ = execute([(0.0, b"show\r\n")])
        self.assertEqual(
            {"ok", "target", "output", "truncated", "timed_out", "aborted"},
            set(result),
        )

    def test_grep_runs_on_timeout_capture(self):
        def serial_factory(clock):
            sent_keep = False

            def read():
                nonlocal sent_keep
                clock.sleep(0.5)
                if not sent_keep:
                    sent_keep = True
                    return b"keep\r\ndrop\r\n"
                return b"x"

            return ScriptedSerial(clock, on_read=read)

        result, _, _ = execute(serial_factory=serial_factory, grep="keep")
        self.assertTrue(result["timed_out"])
        self.assertTrue(result["grepped"])
        self.assertEqual("keep\r\n", result["output"])

    def test_grep_then_trailing_32kib_cap(self):
        line = "hit " + ("x" * 100) + "\r\n"
        payload = (line * 400).encode("utf-8")
        result, _, _ = execute([(0.0, payload)], grep="hit")
        self.assertTrue(result["grepped"])
        self.assertEqual(400, result["match_count"])
        self.assertTrue(result["truncated"])
        self.assertEqual(32 * 1024, len(result["output"].encode("utf-8")))

    def test_grep_matches_trailing_line_without_newline(self):
        result, _, _ = execute([(0.0, b"drop\r\nkeep-error")], grep="error")
        self.assertEqual("keep-error", result["output"])
        self.assertEqual(1, result["match_count"])

    def test_grep_treats_command_echo_as_normal_line(self):
        result, _, _ = execute([(0.0, b"show\r\nanswer\r\n")], grep="show")
        self.assertEqual("show\r\n", result["output"])
        self.assertEqual(1, result["match_count"])

    def test_grep_runs_on_abort_partial_capture(self):
        clock = FakeClock()
        queue = TargetQueue()
        request = queue.enqueue_exec("linux", "show", grep="partial")
        self.assertIs(request, queue.next_write())
        sent_partial = False

        def read():
            nonlocal sent_partial
            if not sent_partial:
                sent_partial = True
                return b"partial noise"
            clock.sleep(0.1)
            if clock.now >= 0.2:
                queue.abort_agents()
            return b""

        serial = ScriptedSerial(clock, on_read=read)
        result = ExecEngine(clock=clock.monotonic, sleep=clock.sleep).execute(
            serial,
            queue,
            request,
            b"\n",
        )

        self.assertFalse(result["ok"])
        self.assertTrue(result["aborted"])
        self.assertTrue(result["grepped"])
        self.assertEqual("partial noise", result["output"])
        self.assertEqual(1, result["match_count"])


class SilentHub:
    def append_log(self, *args, **kwargs):
        pass

    def record_exec_start(self, *args, **kwargs):
        return 1

    def record_exec_end(self, *args, **kwargs):
        pass


class FloodSerial:
    is_open = True

    def write(self, raw):
        pass

    def flush(self):
        pass

    def read(self, _size):
        time.sleep(0.01)
        return b"flood\n"

    def close(self):
        self.is_open = False


class PortWorkerExecWaitTest(unittest.TestCase):
    def test_queued_exec_wait_budget_starts_when_execution_starts(self):
        with (
            patch.object(ExecEngine, "TOTAL_SECONDS", 2.0),
            patch.object(ExecEngine, "IDLE_SECONDS", 0.05),
        ):
            worker = PortWorker("linux", "COM3", 115200, SilentHub())
            worker._ser = FloodSerial()
            worker.is_open = True
            worker.start()
            first = {}
            second = {}
            try:
                first_thread = threading.Thread(
                    target=lambda: first.update(worker.exec("first")),
                    daemon=True,
                )
                first_thread.start()
                self.assertTrue(self._wait_busy(worker))
                queued_at = time.monotonic()
                second_thread = threading.Thread(
                    target=lambda: second.update(worker.exec("second")),
                    daemon=True,
                )
                second_thread.start()
                first_thread.join(10)
                second_thread.join(10)
                queued_waited = time.monotonic() - queued_at
            finally:
                worker.close()

        self.assertFalse(first_thread.is_alive())
        self.assertFalse(second_thread.is_alive())
        self.assertNotEqual(
            second.get("error"),
            "Exec wait exceeded total timeout",
        )
        self.assertTrue(second.get("timed_out"))
        self.assertGreaterEqual(queued_waited, 3.5)

    def _wait_busy(self, worker):
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            if worker.is_busy:
                return True
            time.sleep(0.01)
        return False


class FakeExecWorker:
    def __init__(self):
        self.is_open = True
        self._stop = threading.Event()
        self.calls = []

    def enqueue_exec(
        self,
        cmd,
        prompt=None,
        prompt_is_regex=False,
        grep=None,
        grep_is_regex=False,
        grep_context=0,
    ):
        self.calls.append(
            (cmd, prompt, prompt_is_regex, grep, grep_is_regex, grep_context)
        )
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
        self.assertEqual([("show", "device> ", False, None, False, 0)], worker.calls)

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
