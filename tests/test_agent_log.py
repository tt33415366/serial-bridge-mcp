import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from serial import SerialException

import serial_bridge.app as app_module
from serial_bridge.config import Config
from serial_bridge.hub import Hub, PortWorker
from serial_bridge.hub.queue import exec_result
from serial_bridge.hub.trace import AgentTrace


def make_hub(live_dir=None):
    kwargs = {
        "slots": [
            {"name": "linux", "title": "Linux", "com": "COM3", "baud": 115200},
            {"name": "rtos", "title": "RTOS", "com": "COM6", "baud": 115200},
        ],
        "path": Path("serial_bridge.json"),
    }
    if live_dir is not None:
        kwargs["live_dir"] = live_dir
    return Hub(Config(**kwargs))


class AgentTraceTest(unittest.TestCase):
    def test_record_exec_round_trip_is_newest_first_and_emits_contract(self):
        emitted = []
        trace = AgentTrace(emitted.append)

        with patch("serial_bridge.hub.trace.ts", return_value="09:30:00.123"):
            first = trace.record_start("linux", "one", None)
            trace.record_end(first, "linux", "idle", 100, 10, False, True)
            second = trace.record_start("rtos", "two", "rtos> ")
            trace.record_end(second, "rtos", "prompt", 50, 5, False, True)

        self.assertEqual([second, first], [entry["id"] for entry in trace.get_agent_log()])
        self.assertEqual(
            {
                "id": second,
                "phase": "end",
                "target": "rtos",
                "cmd": "two",
                "prompt": "rtos> ",
                "ts": "09:30:00.123",
                "ended_by": "prompt",
                "ms": 50,
                "bytes": 5,
                "truncated": False,
                "ok": True,
            },
            trace.get_agent_log()[0],
        )
        self.assertEqual(
            {
                "type": "exec",
                "phase": "start",
                "id": first,
                "target": "linux",
                "cmd": "one",
                "prompt": None,
                "ts": "09:30:00.123",
            },
            emitted[0],
        )
        self.assertEqual(
            {
                "type": "exec",
                "phase": "end",
                "id": second,
                "target": "rtos",
                "ended_by": "prompt",
                "ms": 50,
                "bytes": 5,
                "truncated": False,
                "ok": True,
            },
            emitted[-1],
        )

    def test_agent_log_keeps_only_fifty_exec_records(self):
        trace = AgentTrace(lambda _event: None)

        for index in range(51):
            exec_id = trace.record_start("linux", str(index), None)
            trace.record_end(exec_id, "linux", "idle", 1, 0, False, True)

        entries = trace.get_agent_log()

        self.assertEqual(50, len(entries))
        self.assertEqual(51, entries[0]["id"])
        self.assertEqual(2, entries[-1]["id"])


class AgentLogTest(unittest.TestCase):
    def test_record_exec_round_trip_is_newest_first_and_emits_contract(self):
        hub = make_hub()
        emitted = []

        with (
            patch.object(hub, "emit", emitted.append),
            patch("serial_bridge.hub.trace.ts", return_value="09:30:00.123"),
        ):
            first = hub.record_exec_start("linux", "one", None)
            hub.record_exec_end(first, "linux", "idle", 100, 10, False, True)
            second = hub.record_exec_start("rtos", "two", "rtos> ")
            hub.record_exec_end(second, "rtos", "prompt", 50, 5, False, True)

        self.assertEqual([second, first], [entry["id"] for entry in hub.get_agent_log()])
        self.assertEqual(
            {
                "id": second,
                "phase": "end",
                "target": "rtos",
                "cmd": "two",
                "prompt": "rtos> ",
                "ts": "09:30:00.123",
                "ended_by": "prompt",
                "ms": 50,
                "bytes": 5,
                "truncated": False,
                "ok": True,
            },
            hub.get_agent_log()[0],
        )
        self.assertEqual(
            {
                "type": "exec",
                "phase": "start",
                "id": first,
                "target": "linux",
                "cmd": "one",
                "prompt": None,
                "ts": "09:30:00.123",
            },
            emitted[0],
        )
        self.assertEqual(
            {
                "type": "exec",
                "phase": "end",
                "id": second,
                "target": "rtos",
                "ended_by": "prompt",
                "ms": 50,
                "bytes": 5,
                "truncated": False,
                "ok": True,
            },
            emitted[-1],
        )

    def test_agent_log_keeps_only_fifty_exec_records(self):
        hub = make_hub()
        with patch.object(hub, "emit"):
            for index in range(51):
                exec_id = hub.record_exec_start("linux", str(index), None)
                hub.record_exec_end(exec_id, "linux", "idle", 1, 0, False, True)

        entries = hub.get_agent_log()

        self.assertEqual(50, len(entries))
        self.assertEqual(51, entries[0]["id"])
        self.assertEqual(2, entries[-1]["id"])

    def test_agent_log_is_excluded_from_status_and_bridge_status_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            live_dir = Path(temp_dir)
            hub = make_hub(live_dir)
            with patch.object(hub, "emit"):
                hub.record_exec_start("linux", "show", None)
            hub._write_bridge_status()
            persisted = json.loads(
                (live_dir / "bridge_status.json").read_text(encoding="utf-8")
            )

        self.assertNotIn("agent_log", hub.status())
        self.assertNotIn("agent_log", persisted)


class CompletingExecEngine:
    OUTPUT_CAP_BYTES = 32 * 1024
    clock = staticmethod(time.monotonic)

    def execute(self, _serial, _queue, request, _line_ending, **callbacks):
        callbacks["on_rx"](b"completed")
        callbacks["on_done"]("idle")
        return exec_result(request.target, ok=True, output="completed")


class FailingExecEngine:
    clock = staticmethod(time.monotonic)

    def execute(self, _serial, _queue, _request, _line_ending, **_callbacks):
        raise SerialException("device disconnected")


class FakeSerial:
    is_open = True

    def read(self, _size):
        return b""

    def close(self):
        self.is_open = False


class WorkerExecLifecycleTest(unittest.TestCase):
    def test_worker_emits_paired_start_and_end_with_stable_id(self):
        hub = make_hub()
        emitted = []
        worker = PortWorker("linux", "COM3", 115200, hub)
        worker._ser = FakeSerial()
        worker._exec_engine = CompletingExecEngine()
        worker.is_open = True
        request = worker.enqueue_exec("show", prompt="linux> ")

        with patch.object(hub, "emit", emitted.append):
            worker.start()
            try:
                self.assertTrue(request.done.wait(1))
            finally:
                worker.close()

        lifecycle = [message for message in emitted if message["type"] == "exec"]
        self.assertEqual(["start", "end"], [message["phase"] for message in lifecycle])
        self.assertEqual(lifecycle[0]["id"], lifecycle[1]["id"])
        self.assertEqual("linux", lifecycle[0]["target"])
        self.assertEqual("show", lifecycle[0]["cmd"])
        self.assertEqual("idle", lifecycle[1]["ended_by"])
        self.assertEqual(9, lifecycle[1]["bytes"])
        self.assertFalse(lifecycle[1]["truncated"])
        self.assertTrue(lifecycle[1]["ok"])
        self.assertIsInstance(lifecycle[1]["ms"], int)

    def test_serial_exception_during_exec_records_diagnostic_and_closes_worker(self):
        hub = make_hub()
        logs = []
        worker = PortWorker("linux", "COM3", 115200, hub)
        worker._ser = FakeSerial()
        worker._exec_engine = FailingExecEngine()
        worker.is_open = True
        request = worker.enqueue_exec("show")

        with (
            patch.object(hub, "emit"),
            patch.object(hub, "append_log", side_effect=lambda *args, **kwargs: logs.append((args, kwargs))),
        ):
            worker.start()
            try:
                self.assertTrue(request.done.wait(1))
                worker._thread.join(timeout=1)
                self.assertFalse(worker.is_open)
            finally:
                worker.close()

        self.assertEqual("Exec failed", request.result["error"])
        self.assertIn(
            (
                ("linux", "---", "SerialException: device disconnected"),
                {"who": "system"},
            ),
            logs,
        )


class AgentLogApiTest(unittest.TestCase):
    def test_loopback_get_agent_log_returns_entries(self):
        hub = make_hub()
        with patch.object(hub, "emit"):
            exec_id = hub.record_exec_start("linux", "show", None)
            hub.record_exec_end(exec_id, "linux", "idle", 10, 4, False, True)
        client = TestClient(app_module.app, client=("127.0.0.1", 50000))

        with patch.object(app_module, "hub", hub):
            response = client.get("/api/agent_log")

        self.assertEqual(200, response.status_code)
        self.assertEqual({"ok": True, "entries": hub.get_agent_log()}, response.json())

    def test_non_loopback_get_agent_log_is_rejected(self):
        client = TestClient(app_module.app, client=("192.0.2.10", 50000))

        response = client.get("/api/agent_log")

        self.assertEqual(403, response.status_code)


if __name__ == "__main__":
    unittest.main()
