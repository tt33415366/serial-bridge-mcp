import re
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import serial_bridge.hub as hub_module
from serial_bridge.config import Config, DEFAULT_LIVE_DIR
from serial_bridge.hub import Hub


def make_config(path=Path("serial_bridge.json"), live_dir=None):
    kwargs = {
        "slots": [
            {"name": "linux", "title": "Linux", "com": "COM3", "baud": 115200},
            {"name": "rtos", "title": "RTOS", "com": "COM6", "baud": 115200},
        ],
        "path": path,
    }
    if live_dir is not None:
        kwargs["live_dir"] = live_dir
    return Config(**kwargs)

class FakePortWorker:
    instances = []

    def __init__(self, name, port, baud, hub_ref):
        self.name = name
        self.port = port
        self.baud = baud
        self.hub = hub_ref
        self.is_open = False
        self.sent = []
        self.closed = False
        self.events = []
        self.is_busy = False
        self.__class__.instances.append(self)

    def open(self):
        self.is_open = True

    def start(self):
        pass

    def close(self):
        self.events.append(("close", self.hub.mode))
        self.closed = True
        self.is_open = False

    def abort_agent_work(self):
        self.events.append(("abort", self.hub.mode))

    def send(self, cmd, who="user", raw=None):
        self.sent.append((cmd, who, raw))


class WorkerHub:
    def __init__(self, fail_tx_log=False):
        self.fail_tx_log = fail_tx_log

    def append_log(self, target, direction, text, who=""):
        if direction == ">>>" and self.fail_tx_log:
            self.fail_tx_log = False
            raise RuntimeError("TX log failed")


class FakeSerial:
    def __init__(self, events=None, fail_stage=None):
        self.events = events if events is not None else []
        self.fail_stage = fail_stage
        self.is_open = True
        self.second_write_started = threading.Event()
        self.writes = []

    def write(self, raw):
        self.events.append("write")
        self.writes.append(raw)
        if raw.startswith(b"second"):
            self.second_write_started.set()
        if self.fail_stage == "write":
            self.fail_stage = None
            raise RuntimeError("write failed")

    def flush(self):
        if self.fail_stage == "flush":
            self.fail_stage = None
            raise RuntimeError("flush failed")

    def read(self, size):
        return b""

    def close(self):
        self.is_open = False


class PausingAbortEvent:
    def __init__(self):
        self._set = False
        self.checked = threading.Event()
        self.release_check = threading.Event()

    def is_set(self):
        snapshot = self._set
        self.checked.set()
        self.release_check.wait(1)
        return snapshot

    def set(self):
        self._set = True


class TargetQueueTest(unittest.TestCase):
    def test_agent_writes_are_fifo(self):
        queue = hub_module.TargetQueue()

        first = queue.enqueue("first", "agent")
        second = queue.enqueue("second", "agent")

        self.assertIs(first, queue.next_write())
        queue.complete(first)
        self.assertIs(second, queue.next_write())

    def test_operator_write_barges_ahead_of_queued_agent_writes(self):
        queue = hub_module.TargetQueue()

        first = queue.enqueue("first", "agent")
        queue.enqueue("second", "agent")
        operator = queue.enqueue("interrupt", "user")

        self.assertIs(operator, queue.next_write())
        queue.complete(operator)
        self.assertIs(first, queue.next_write())

    def test_abort_marks_active_and_queued_agent_work(self):
        queue = hub_module.TargetQueue()
        active = queue.enqueue("active", "agent")
        queued = queue.enqueue("queued", "agent")
        operator = queue.enqueue("operator", "operator")
        self.assertIs(operator, queue.next_write())
        queue.complete(operator)
        self.assertIs(active, queue.next_write())

        queue.abort_agents()

        self.assertTrue(active.aborted.is_set())
        self.assertTrue(queued.aborted.is_set())
        self.assertIsNone(queue.next_write())

    def test_raw_send_keeps_fifo_order_with_exec(self):
        queue = hub_module.TargetQueue()

        text = queue.enqueue("first", "agent")
        execution = queue.enqueue_exec("linux", "show")
        raw = queue.enqueue("", "agent", raw=b"\x03")

        self.assertIs(text, queue.next_write())
        queue.complete(text)
        self.assertIs(execution, queue.next_write())
        queue.complete(execution)
        self.assertIs(raw, queue.next_write())
        self.assertEqual(b"\x03", raw.raw)


class PortWorkerTest(unittest.TestCase):
    def test_raw_send_writes_exact_bytes_without_line_ending(self):
        worker = hub_module.PortWorker("linux", "COM3", 115200, WorkerHub())
        serial = FakeSerial()
        worker._ser = serial
        request = worker._tx.enqueue("", "agent", raw=b"\x03")
        self.assertIs(request, worker._tx.next_write())

        worker._write_request(request)

        self.assertEqual([b"\x03"], serial.writes)

    def test_crt_abort_linearizes_before_any_subsequent_agent_write(self):
        events = []
        worker = hub_module.PortWorker("linux", "COM3", 115200, WorkerHub())
        serial = FakeSerial(events)
        worker._ser = serial
        worker.is_open = True
        request = worker._tx.enqueue("agent command", "agent")
        request.aborted = PausingAbortEvent()
        worker.start()

        try:
            self.assertTrue(request.aborted.checked.wait(1))
            abort_done = threading.Event()

            def abort():
                worker.abort_agent_work()
                events.append("abort returned")
                abort_done.set()

            abort_thread = threading.Thread(target=abort)
            abort_thread.start()
            abort_done.wait(0.1)
            request.aborted.release_check.set()
            abort_thread.join(1)

            self.assertTrue(abort_done.is_set())
            if "write" in events:
                self.assertLess(events.index("write"), events.index("abort returned"))
        finally:
            request.aborted.release_check.set()
            worker.close()

    def test_tx_failures_do_not_stall_agent_fifo(self):
        for fail_stage in ("write", "flush", "log"):
            with self.subTest(fail_stage=fail_stage):
                hub = WorkerHub(fail_tx_log=fail_stage == "log")
                worker = hub_module.PortWorker("linux", "COM3", 115200, hub)
                serial = FakeSerial(fail_stage=None if fail_stage == "log" else fail_stage)
                worker._ser = serial
                worker.is_open = True
                worker.send("first", who="agent")
                worker.send("second", who="agent")
                worker.start()

                try:
                    self.assertTrue(serial.second_write_started.wait(1))
                finally:
                    worker.close()


class HubTest(unittest.TestCase):
    def setUp(self):
        FakePortWorker.instances.clear()

    def test_starts_in_crt_mode_without_opening_ports(self):
        hub = Hub(make_config())

        self.assertEqual("crt", hub.status()["mode"])
        self.assertEqual({}, hub.workers)
        self.assertFalse(hub.status()["ports"]["linux"]["open"])
        self.assertFalse(hub.status()["ports"]["rtos"]["open"])

    def test_resolve_target_normalizes_case_and_rejects_unknown(self):
        hub = Hub(make_config())

        self.assertEqual(("linux", None), hub.resolve_target("Linux"))
        self.assertEqual(("rtos", None), hub.resolve_target("  RTOS  "))
        name, error = hub.resolve_target("Missing")
        self.assertEqual("missing", name)
        self.assertIn("unknown target 'missing'", error)
        self.assertEqual(
            (None, "target must be a Target Name string"),
            hub.resolve_target(42),
        )

    def test_status_and_bridge_use_configured_port_bindings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            live = Path(temp_dir)
            config = Config(
                slots=[
                    {"name": "linux", "title": "Linux", "com": "COM8", "baud": 57600},
                    {"name": "rtos", "title": "RTOS", "com": "COM9", "baud": 230400},
                ],
                path=live / "serial_bridge.json",
                live_dir=live,
            )
            with patch.object(hub_module, "PortWorker", FakePortWorker):
                hub = Hub(config)

                self.assertEqual("linux", hub.status()["ports"]["linux"]["name"])
                self.assertEqual("Linux", hub.status()["ports"]["linux"]["title"])
                self.assertEqual("COM8", hub.status()["ports"]["linux"]["com"])
                self.assertEqual(57600, hub.status()["ports"]["linux"]["baud"])
                self.assertEqual("COM9", hub.status()["ports"]["rtos"]["com"])
                self.assertEqual(230400, hub.status()["ports"]["rtos"]["baud"])

                hub.start_bridge()

                self.assertEqual(
                    [("linux", "COM8", 57600), ("rtos", "COM9", 230400)],
                    [
                        (worker.name, worker.port, worker.baud)
                        for worker in FakePortWorker.instances
                    ],
                )
                self.assertFalse(hub.status()["ports"]["linux"]["busy"])
                hub.workers["linux"].is_busy = True
                self.assertTrue(hub.status()["ports"]["linux"]["busy"])

    def test_status_reads_a_consistent_worker_snapshot(self):
        class ClearingWorkers(dict):
            """Mimics stop_bridge() clearing workers between two reads."""

            def __contains__(self, key):
                present = super().__contains__(key)
                self.clear()
                return present

        hub = Hub(make_config())
        worker = FakePortWorker("linux", "COM3", 115200, hub)
        worker.is_open = True
        hub.workers = ClearingWorkers(linux=worker)

        status = hub.status()

        self.assertTrue(status["ports"]["linux"]["open"])
        self.assertFalse(status["ports"]["rtos"]["open"])

    def test_status_surfaces_config_warning(self):
        config = Config(
            slots=[
                {"name": "linux", "title": "Linux", "com": "COM3", "baud": 115200},
                {"name": "rtos", "title": "RTOS", "com": "COM6", "baud": 115200},
            ],
            path=Path("serial_bridge.json"),
            warning="Could not load config serial_bridge.json: invalid JSON",
        )

        status = Hub(config).status()

        self.assertEqual(config.warning, status["config_warning"])

    def test_bridge_mode_opens_sends_and_releases_both_targets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            live = Path(temp_dir)
            with patch.object(hub_module, "PortWorker", FakePortWorker):
                hub = Hub(make_config(live / "serial_bridge.json", live_dir=live))

                self.assertEqual(
                    {"ok": True, "mode": "bridge"},
                    hub.start_bridge(),
                )
                self.assertEqual(
                    {
                        "ok": True,
                        "target": "linux",
                        "cmd": "uname -a",
                        "who": "agent",
                    },
                    hub.send("linux", "uname -a", who="agent"),
                )
                self.assertEqual([("uname -a", "agent", None)], hub.workers["linux"].sent)

                self.assertEqual(
                    {"ok": True, "mode": "crt"},
                    hub.stop_bridge(),
                )
                self.assertEqual({}, hub.workers)
                self.assertTrue(all(worker.closed for worker in FakePortWorker.instances))
                self.assertTrue(
                    all(
                        worker.events == [("abort", "crt"), ("close", "crt")]
                        for worker in FakePortWorker.instances
                    )
                )

    def test_invalid_raw_hex_is_rejected_without_enqueue(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            live = Path(temp_dir)
            with patch.object(hub_module, "PortWorker", FakePortWorker):
                hub = Hub(make_config(live / "serial_bridge.json", live_dir=live))
                hub.start_bridge()

                result = hub.send("linux", raw_hex="not hex", who="agent")

                self.assertFalse(result["ok"])
                self.assertIn("hex", result["error"].lower())
                self.assertEqual([], hub.workers["linux"].sent)

    def test_stop_bridge_cannot_miss_concurrent_send_enqueue(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            live = Path(temp_dir)
            hub = Hub(make_config(live / "serial_bridge.json", live_dir=live))
            worker = FakePortWorker("linux", "COM3", 115200, hub)
            worker.is_open = True
            hub.mode = "bridge"
            hub.workers["linux"] = worker
            enqueue_entered = threading.Event()
            release_enqueue = threading.Event()
            stop_finished = threading.Event()

            def pausing_send(cmd, who="user", raw=None):
                enqueue_entered.set()
                release_enqueue.wait(1)
                worker.sent.append((cmd, who, raw))

            def abort_agent_work():
                worker.sent.clear()

            worker.send = pausing_send
            worker.abort_agent_work = abort_agent_work
            result = {}
            send_thread = threading.Thread(
                target=lambda: result.update(hub.send("linux", "show", who="agent")),
                daemon=True,
            )
            stop_thread = threading.Thread(
                target=lambda: (hub.stop_bridge(), stop_finished.set()),
                daemon=True,
            )

            with patch.object(hub_module, "PortWorker", FakePortWorker):
                send_thread.start()
                self.assertTrue(enqueue_entered.wait(1))
                stop_thread.start()
                self.assertFalse(stop_finished.wait(0.1))
                release_enqueue.set()
                stop_thread.join(1)
                send_thread.join(1)

            self.assertFalse(send_thread.is_alive())
            self.assertFalse(stop_thread.is_alive())
            self.assertTrue(result["ok"])
            self.assertEqual([], worker.sent)

    def test_binding_update_waits_for_start_and_is_rejected_after_open(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            live = Path(temp_dir)
            open_entered = threading.Event()
            release_open = threading.Event()
            update_finished = threading.Event()

            class PausingOpenWorker(FakePortWorker):
                def open(self):
                    open_entered.set()
                    release_open.wait(1)
                    super().open()

            hub = Hub(make_config(live / "serial_bridge.json", live_dir=live))
            start_result = {}
            update_result = {}
            start_thread = threading.Thread(
                target=lambda: start_result.update(hub.start_bridge()),
                daemon=True,
            )
            update_thread = threading.Thread(
                target=lambda: (
                    update_result.update(
                        hub.update_slots(
                            [
                                {
                                    "name": "linux",
                                    "title": "Linux",
                                    "com": "COM8",
                                    "baud": 57600,
                                },
                                {
                                    "name": "rtos",
                                    "title": "RTOS",
                                    "com": "COM9",
                                    "baud": 230400,
                                },
                            ]
                        )
                    ),
                    update_finished.set(),
                ),
                daemon=True,
            )

            with (
                patch.object(hub_module, "PortWorker", PausingOpenWorker),
            ):
                start_thread.start()
                self.assertTrue(open_entered.wait(1))
                update_thread.start()
                self.assertFalse(update_finished.wait(0.1))
                release_open.set()
                start_thread.join(1)
                update_thread.join(1)

            self.assertFalse(start_thread.is_alive())
            self.assertFalse(update_thread.is_alive())
            self.assertTrue(start_result["ok"])
            self.assertFalse(update_result["ok"])
            self.assertEqual("COM3", hub.ports["linux"]["com"])
            self.assertFalse((live / "serial_bridge.json").exists())

    def test_binding_update_waits_until_stop_finishes_closing_ports(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            live = Path(temp_dir)
            hub = Hub(make_config(live / "serial_bridge.json", live_dir=live))
            worker = FakePortWorker("linux", "COM3", 115200, hub)
            worker.is_open = True
            hub.mode = "bridge"
            hub.workers["linux"] = worker
            close_entered = threading.Event()
            release_close = threading.Event()
            update_finished = threading.Event()
            original_close = worker.close

            def pausing_close():
                close_entered.set()
                release_close.wait(1)
                original_close()

            worker.close = pausing_close
            update_result = {}
            stop_thread = threading.Thread(target=hub.stop_bridge, daemon=True)
            update_thread = threading.Thread(
                target=lambda: (
                    update_result.update(
                        hub.update_slots(
                            [
                                {
                                    "name": "linux",
                                    "title": "Linux",
                                    "com": "COM8",
                                    "baud": 57600,
                                },
                                {
                                    "name": "rtos",
                                    "title": "RTOS",
                                    "com": "COM9",
                                    "baud": 230400,
                                },
                            ]
                        )
                    ),
                    update_finished.set(),
                ),
                daemon=True,
            )

            stop_thread.start()
            self.assertTrue(close_entered.wait(1))
            update_thread.start()
            self.assertFalse(update_finished.wait(0.1))
            self.assertFalse((live / "serial_bridge.json").exists())
            release_close.set()
            stop_thread.join(1)
            update_thread.join(1)

            self.assertFalse(stop_thread.is_alive())
            self.assertFalse(update_thread.is_alive())
            self.assertTrue(worker.closed)
            self.assertTrue(update_result["ok"])
            self.assertEqual("COM8", hub.ports["linux"]["com"])

    def test_rename_uses_new_name_on_next_bridge_and_leaves_old_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            live = Path(temp_dir)
            with patch.object(hub_module, "PortWorker", FakePortWorker):
                hub = Hub(make_config(live / "serial_bridge.json", live_dir=live))
                session_time = datetime(2026, 8, 18, 15, 4, 5)
                with patch.object(hub_module, "datetime") as mock_dt:
                    mock_dt.now.return_value = session_time
                    hub.start_bridge()
                old_log = live / "linux-2026-08-18-150405.log"
                hub.append_log("linux", "<<<", "before rename")
                self.assertTrue(old_log.is_file())
                hub.stop_bridge()

                result = hub.update_slots(
                    [
                        {
                            "name": "embedded",
                            "title": "Embedded Linux",
                            "com": "COM3",
                            "baud": 115200,
                        },
                        {
                            "name": "rtos",
                            "title": "RTOS",
                            "com": "COM6",
                            "baud": 115200,
                        },
                    ]
                )

                self.assertTrue(result["ok"])
                self.assertNotIn("linux", hub.ports)
                self.assertIn("embedded", hub.ports)
                self.assertTrue(old_log.is_file())
                self.assertIn("before rename", old_log.read_text(encoding="utf-8"))

                with patch.object(hub_module, "datetime") as mock_dt:
                    mock_dt.now.return_value = datetime(2026, 8, 18, 16, 0, 0)
                    hub.start_bridge()
                new_log = live / "embedded-2026-08-18-160000.log"
                hub.append_log("embedded", "<<<", "after rename")
                self.assertTrue(new_log.is_file())
                self.assertIn("after rename", new_log.read_text(encoding="utf-8"))

    def test_display_title_can_change_in_bridge_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            live = Path(temp_dir)
            with patch.object(hub_module, "PortWorker", FakePortWorker):
                hub = Hub(make_config(live / "serial_bridge.json", live_dir=live))
                hub.start_bridge()
                result = hub.update_slots(
                    [
                        {
                            "name": "linux",
                            "title": "Main Console",
                            "com": "COM3",
                            "baud": 115200,
                        },
                        {
                            "name": "rtos",
                            "title": "RTOS",
                            "com": "COM6",
                            "baud": 115200,
                        },
                    ]
                )

                self.assertTrue(result["ok"])
                self.assertEqual(
                    "Main Console",
                    hub.status()["ports"]["linux"]["title"],
                )

    def test_port_binding_changes_rejected_in_bridge_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            live = Path(temp_dir)
            with patch.object(hub_module, "PortWorker", FakePortWorker):
                hub = Hub(make_config(live / "serial_bridge.json", live_dir=live))
                hub.start_bridge()
                result = hub.update_slots(
                    [
                        {
                            "name": "linux",
                            "title": "Linux",
                            "com": "COM8",
                            "baud": 115200,
                        },
                        {
                            "name": "rtos",
                            "title": "RTOS",
                            "com": "COM6",
                            "baud": 115200,
                        },
                    ]
                )

                self.assertFalse(result["ok"])
                self.assertEqual("COM3", hub.ports["linux"]["com"])


class HubTailTest(unittest.TestCase):
    def test_get_tail_returns_empty_when_log_unset(self):
        hub = Hub(make_config())
        self.assertEqual({"linux": "", "rtos": ""}, hub.get_tail())

    def test_get_tail_returns_empty_when_log_path_missing(self):
        hub = Hub(make_config())
        hub.ports["linux"]["log"] = Path("missing-session.log")
        self.assertEqual({"linux": "", "rtos": ""}, hub.get_tail())

    def test_get_tail_returns_last_n_lines_for_single_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log = Path(temp_dir) / "linux.log"
            log.write_text("\n".join(f"line{i}" for i in range(100)), encoding="utf-8")
            hub = Hub(make_config())
            hub.ports["linux"]["log"] = log

            result = hub.get_tail(target="linux", n=5)

        self.assertEqual({"linux": "\n".join(f"line{i}" for i in range(95, 100))}, result)

    def test_get_tail_reads_both_targets_by_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            linux_log = Path(temp_dir) / "linux.log"
            rtos_log = Path(temp_dir) / "rtos.log"
            linux_log.write_text("linux line\n", encoding="utf-8")
            rtos_log.write_text("rtos line\n", encoding="utf-8")
            hub = Hub(make_config())
            hub.ports["linux"]["log"] = linux_log
            hub.ports["rtos"]["log"] = rtos_log

            result = hub.get_tail()

        self.assertEqual({"linux": "linux line", "rtos": "rtos line"}, result)


class LiveDirectoryTest(unittest.TestCase):
    def setUp(self):
        FakePortWorker.instances.clear()

    def test_status_exposes_live_dir_and_empty_log_before_bridge(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            live = Path(temp_dir)
            hub = Hub(make_config(live / "serial_bridge.json", live_dir=live))
            status = hub.status()

            self.assertEqual(str(live.resolve()), status["live_dir"])
            self.assertEqual("", status["ports"]["linux"]["log"])
            self.assertEqual("", status["ports"]["rtos"]["log"])

    def test_bridge_creates_session_log_files_with_shared_timestamp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            live = Path(temp_dir)
            with patch.object(hub_module, "PortWorker", FakePortWorker):
                hub = Hub(make_config(live / "serial_bridge.json", live_dir=live))
                session_time = datetime(2026, 8, 18, 9, 30, 45)
                with patch.object(hub_module, "datetime") as mock_dt:
                    mock_dt.now.return_value = session_time
                    self.assertTrue(hub.start_bridge()["ok"])

                linux_log = live / "linux-2026-08-18-093045.log"
                rtos_log = live / "rtos-2026-08-18-093045.log"
                self.assertTrue(linux_log.is_file())
                self.assertTrue(rtos_log.is_file())
                status = hub.status()
                self.assertEqual(str(linux_log.resolve()), status["ports"]["linux"]["log"])
                self.assertEqual(str(rtos_log.resolve()), status["ports"]["rtos"]["log"])
                self.assertTrue((live / "bridge_status.json").is_file())

    def test_second_bridge_session_creates_distinct_log_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            live = Path(temp_dir)
            with patch.object(hub_module, "PortWorker", FakePortWorker):
                hub = Hub(make_config(live / "serial_bridge.json", live_dir=live))
                first_time = datetime(2026, 8, 18, 9, 0, 0)
                second_time = datetime(2026, 8, 18, 10, 0, 0)
                with patch.object(hub_module, "datetime") as mock_dt:
                    mock_dt.now.return_value = first_time
                    hub.start_bridge()
                    first_linux = live / "linux-2026-08-18-090000.log"
                    hub.stop_bridge()
                    mock_dt.now.return_value = second_time
                    hub.start_bridge()
                    second_linux = live / "linux-2026-08-18-100000.log"

                self.assertTrue(first_linux.is_file())
                self.assertTrue(second_linux.is_file())
                self.assertNotEqual(first_linux, second_linux)

    def test_stop_bridge_retains_session_log_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            live = Path(temp_dir)
            with patch.object(hub_module, "PortWorker", FakePortWorker):
                hub = Hub(make_config(live / "serial_bridge.json", live_dir=live))
                session_time = datetime(2026, 8, 18, 9, 30, 45)
                with patch.object(hub_module, "datetime") as mock_dt:
                    mock_dt.now.return_value = session_time
                    hub.start_bridge()
                    expected = live / "linux-2026-08-18-093045.log"
                    hub.stop_bridge()

                self.assertEqual(expected, hub.ports["linux"]["log"])
                self.assertEqual(str(expected.resolve()), hub.status()["ports"]["linux"]["log"])

    def test_changing_live_dir_does_not_migrate_old_logs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            old_live = Path(temp_dir) / "old"
            new_live = Path(temp_dir) / "new"
            with patch.object(hub_module, "PortWorker", FakePortWorker):
                hub = Hub(make_config(Path(temp_dir) / "serial_bridge.json", live_dir=old_live))
                session_time = datetime(2026, 8, 18, 11, 0, 0)
                with patch.object(hub_module, "datetime") as mock_dt:
                    mock_dt.now.return_value = session_time
                    hub.start_bridge()
                old_log = old_live / "linux-2026-08-18-110000.log"
                hub.append_log("linux", "<<<", "old dir")
                hub.stop_bridge()

                hub.config.live_dir = new_live
                with patch.object(hub_module, "datetime") as mock_dt:
                    mock_dt.now.return_value = datetime(2026, 8, 18, 12, 0, 0)
                    hub.start_bridge()
                new_log = new_live / "linux-2026-08-18-120000.log"

                self.assertTrue(old_log.is_file())
                self.assertIn("old dir", old_log.read_text(encoding="utf-8"))
                self.assertTrue(new_log.is_file())
                self.assertFalse((new_live / old_log.name).exists())

    def test_mkdir_failure_keeps_crt_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            live = Path(temp_dir) / "blocked"
            hub = Hub(make_config(Path(temp_dir) / "serial_bridge.json", live_dir=live))
            with (
                patch.object(hub_module, "PortWorker", FakePortWorker),
                patch.object(Path, "mkdir", side_effect=OSError("permission denied")),
            ):
                result = hub.start_bridge()

            self.assertFalse(result["ok"])
            self.assertEqual("crt", hub.mode)
            self.assertIn("Live Directory", result["error"])


class TranscriptEscapeTest(unittest.TestCase):
    def test_log_file_is_plain_text_while_ui_keeps_color_escapes(self):
        colored = "\x1b[1;34mbin\x1b[m\tdata\x08\x1b[2K"
        with tempfile.TemporaryDirectory() as temp_dir:
            live = Path(temp_dir)
            with patch.object(hub_module, "PortWorker", FakePortWorker):
                hub = Hub(make_config(live / "serial_bridge.json", live_dir=live))
                session_time = datetime(2026, 8, 18, 14, 0, 0)
                with patch.object(hub_module, "datetime") as mock_dt:
                    mock_dt.now.return_value = session_time
                    hub.start_bridge()
                emitted = []
                with patch.object(hub, "emit", emitted.append):
                    hub.append_log("linux", "<<<", colored)

                logged = (live / "linux-2026-08-18-140000.log").read_text(encoding="utf-8")

        self.assertTrue(logged.endswith(" bin\tdata\n"), logged)
        self.assertNotIn("\x1b", logged)
        self.assertNotIn("\x08", logged)
        self.assertEqual("\x1b[1;34mbin\x1b[m\tdata\x1b[2K", emitted[0]["text"])

    def test_sanitizers_keep_newlines_and_tabs(self):
        self.assertEqual("a\tb\r\nc", hub_module.strip_ansi("a\tb\r\nc"))
        self.assertEqual("a\tb\r\nc", hub_module.sanitize_display("a\tb\r\nc"))


class AvailablePortsTest(unittest.TestCase):
    def test_ports_are_numerically_sorted_with_descriptions(self):
        detected = [
            SimpleNamespace(device="COM10", description="USB Serial Port (COM10)"),
            SimpleNamespace(device="COM2", description=None),
        ]
        with patch.object(hub_module.list_ports, "comports", return_value=detected):
            ports = hub_module.available_ports()

        self.assertEqual(
            [
                {"com": "COM2", "label": ""},
                {"com": "COM10", "label": "USB Serial Port"},
            ],
            ports,
        )


if __name__ == "__main__":
    unittest.main()
