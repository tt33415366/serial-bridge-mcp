import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from serial_bridge.config import Config
from serial_bridge.hub import Hub
from serial_bridge.hub.transcript import Transcript


def make_ports():
    return {
        "linux": {"title": "Linux", "log": None},
        "rtos": {"title": "RTOS", "log": None},
    }


def make_hub(live_dir):
    return Hub(
        Config(
            slots=[
                {"name": "linux", "title": "Linux", "com": "COM3", "baud": 115200},
                {"name": "rtos", "title": "RTOS", "com": "COM6", "baud": 115200},
            ],
            path=live_dir / "serial_bridge.json",
            live_dir=live_dir,
        )
    )


class TranscriptTest(unittest.TestCase):
    def test_assign_session_logs_creates_shared_timestamp_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            live_dir = Path(temp_dir)
            ports = make_ports()
            transcript = Transcript(
                lambda: ports,
                lambda: live_dir,
                lambda _event: None,
                lambda: datetime(2026, 8, 19, 9, 30, 45),
            )

            transcript.assign_session_logs()

            self.assertEqual(
                live_dir / "linux-2026-08-19-093045.log",
                ports["linux"]["log"],
            )
            self.assertEqual(
                live_dir / "rtos-2026-08-19-093045.log",
                ports["rtos"]["log"],
            )
            self.assertTrue(ports["linux"]["log"].is_file())
            self.assertTrue(ports["rtos"]["log"].is_file())

    def test_append_log_writes_plain_text_and_emits_console_line(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            live_dir = Path(temp_dir)
            ports = make_ports()
            emitted = []
            transcript = Transcript(
                lambda: ports,
                lambda: live_dir,
                emitted.append,
                lambda: datetime(2026, 8, 19, 9, 30, 45, 123000),
            )
            transcript.assign_session_logs()

            with patch("serial_bridge.hub.transcript.ts", return_value="09:30:45.123"):
                transcript.append_log(
                    "linux",
                    "<<<",
                    "\x1b[1;34mbin\x1b[m\tdata\x08\x1b[2K",
                    who="agent",
                )

            logged = ports["linux"]["log"].read_text(encoding="utf-8")
            self.assertEqual(
                "2026-08-19 09:30:45.123 <<< [LINUX] (agent) bin\tdata\n",
                logged,
            )
            self.assertEqual(
                {
                    "type": "line",
                    "target": "linux",
                    "direction": "<<<",
                    "who": "agent",
                    "text": "\x1b[1;34mbin\x1b[m\tdata\x1b[2K",
                    "ts": "09:30:45.123",
                },
                emitted[0],
            )

    def test_get_tail_reads_requested_lines_and_preserves_missing_targets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            live_dir = Path(temp_dir)
            ports = make_ports()
            linux_log = live_dir / "linux.log"
            linux_log.write_text(
                "\n".join(f"line{index}" for index in range(5)),
                encoding="utf-8",
            )
            ports["linux"]["log"] = linux_log
            transcript = Transcript(
                lambda: ports,
                lambda: live_dir,
                lambda _event: None,
                datetime.now,
            )

            result = transcript.get_tail(n=2)

            self.assertEqual({"linux": "line3\nline4", "rtos": ""}, result)


class HubTranscriptDelegationTest(unittest.TestCase):
    def test_hub_transcript_facade_delegates_public_and_assignment_methods(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            hub = make_hub(Path(temp_dir))
            session_time = datetime(2026, 8, 19, 10, 0, 0)
            with (
                patch.object(hub._transcript, "append_log") as append_log,
                patch.object(
                    hub._transcript,
                    "get_tail",
                    return_value={"linux": "tail"},
                ) as get_tail,
                patch.object(
                    hub._transcript,
                    "session_log_path",
                    return_value=Path(temp_dir) / "linux.log",
                ) as session_log_path,
                patch.object(hub._transcript, "assign_session_logs") as assign_logs,
            ):
                hub.append_log("linux", "<<<", "line", who="agent")
                result = hub.get_tail("linux", 10)
                path = hub._session_log_path("linux", session_time)
                hub._assign_session_logs(session_time)

            append_log.assert_called_once_with("linux", "<<<", "line", "agent")
            get_tail.assert_called_once_with("linux", 10)
            session_log_path.assert_called_once_with("linux", session_time)
            assign_logs.assert_called_once_with(session_time)
            self.assertEqual({"linux": "tail"}, result)
            self.assertEqual(Path(temp_dir) / "linux.log", path)


if __name__ == "__main__":
    unittest.main()
