import unittest
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import serial_bridge.app as app_module
import serial_bridge.operator as bridge_operator
from conftest import FakeHub
from serial_bridge.app import ws_endpoint
from serial_bridge.config import Config, load_config
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient
from serial_bridge.hub import Hub
from serial_bridge.token_store import init_token_store, reset_token_store


def _binding_slots(**overrides):
    slots = overrides.get(
        "slots",
        [
            {"name": "linux", "title": "Linux", "com": "COM8", "baud": 57600},
            {"name": "rtos", "title": "RTOS", "com": "COM9", "baud": 230400},
        ],
    )
    payload = {"slots": slots}
    if "live_dir" in overrides:
        payload["live_dir"] = overrides["live_dir"]
    return payload


class FakeWebSocket:
    def __init__(self, message, host="127.0.0.1", authorization=None, origin=None):
        self.message = message
        self.sent = []
        self.received = False
        self.accepted = False
        self.closed = []
        self.client = SimpleNamespace(host=host)
        self.headers = {}
        if authorization is not None:
            self.headers["authorization"] = authorization
        if origin is not None:
            self.headers["origin"] = origin

    async def accept(self):
        self.accepted = True

    async def close(self, code=1000):
        self.closed.append(code)

    async def send_text(self, message):
        self.sent.append(json.loads(message))

    async def receive_text(self):
        if self.received:
            raise WebSocketDisconnect()
        self.received = True
        return json.dumps(self.message)


class AppSendTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.token_temp_dir = tempfile.TemporaryDirectory()
        init_token_store(
            config_path=Path(self.token_temp_dir.name) / "serial_bridge.json",
            environ={},
        )

    def tearDown(self):
        reset_token_store()
        self.token_temp_dir.cleanup()

    def test_operator_routes_live_in_operator_module(self):
        self.assertTrue(callable(bridge_operator.register_operator_routes))
        self.assertTrue(callable(bridge_operator.ws_endpoint))
        self.assertFalse(hasattr(app_module, "api_send"))
        self.assertFalse(hasattr(app_module, "api_bindings"))
        self.assertFalse(hasattr(app_module, "_send"))

    async def test_http_send_normalizes_mixed_case_target_name(self):
        fake_hub = FakeHub()
        client = TestClient(app_module.app, client=("127.0.0.1", 50000))
        with patch.object(app_module, "hub", fake_hub):
            response = client.post(
                "/api/send",
                json={"target": "Linux", "cmd": "uname -a"},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {"ok": True, "target": "linux", "cmd": "uname -a", "who": "user"},
            response.json(),
        )
        self.assertEqual([("linux", "uname -a", "user", None)], fake_hub.calls)

    async def test_websocket_send_normalizes_mixed_case_target_name(self):
        fake_hub = FakeHub()
        ws = FakeWebSocket(
            {"type": "send", "target": "Linux", "cmd": "uname -a"}
        )
        with patch.object(app_module, "hub", fake_hub):
            await ws_endpoint(ws)

        self.assertEqual(
            {
                "type": "ack",
                "ok": True,
                "target": "linux",
                "cmd": "uname -a",
                "who": "user",
            },
            ws.sent[-1],
        )
        self.assertEqual([("linux", "uname -a", "user", None)], fake_hub.calls)

    async def test_http_send_rejects_com_alias(self):
        fake_hub = FakeHub()
        client = TestClient(app_module.app, client=("127.0.0.1", 50000))
        with patch.object(app_module, "hub", fake_hub):
            response = client.post(
                "/api/send",
                json={"target": "COM3", "cmd": "uname -a"},
            )

        self.assertFalse(response.json()["ok"])
        self.assertIn("unknown target", response.json()["error"])
        self.assertEqual([], fake_hub.calls)

    async def test_websocket_send_rejects_com_alias(self):
        fake_hub = FakeHub()
        ws = FakeWebSocket(
            {"type": "send", "target": "COM6", "cmd": "help", "who": "agent"}
        )
        with patch.object(app_module, "hub", fake_hub):
            await ws_endpoint(ws)

        self.assertFalse(ws.sent[-1]["ok"])
        self.assertIn("unknown target", ws.sent[-1]["error"])
        self.assertEqual([], fake_hub.calls)

    async def test_websocket_non_loopback_send_requires_token(self):
        fake_hub = FakeHub()
        ws = FakeWebSocket(
            {"type": "send", "target": "linux", "cmd": "uname -a"},
            host="192.0.2.10",
        )
        with (
            patch.object(app_module, "hub", fake_hub),
            patch.dict("os.environ", {"SERIAL_BRIDGE_TOKEN": "secret"}, clear=False),
        ):
            await ws_endpoint(ws)

        self.assertEqual(
            {"type": "ack", "ok": False, "error": "Unauthorized"},
            ws.sent[-1],
        )
        self.assertEqual([], fake_hub.calls)

    async def test_websocket_non_loopback_send_accepts_bearer_token(self):
        fake_hub = FakeHub()
        ws = FakeWebSocket(
            {"type": "send", "target": "linux", "cmd": "uname -a"},
            host="192.0.2.10",
            authorization="Bearer secret",
        )
        with (
            patch.object(app_module, "hub", fake_hub),
            patch.dict("os.environ", {"SERIAL_BRIDGE_TOKEN": "secret"}, clear=False),
        ):
            await ws_endpoint(ws)

        self.assertEqual(
            {
                "type": "ack",
                "ok": True,
                "target": "linux",
                "cmd": "uname -a",
                "who": "agent",
            },
            ws.sent[-1],
        )
        self.assertEqual([("linux", "uname -a", "agent", None)], fake_hub.calls)

    async def test_websocket_ignores_client_supplied_who(self):
        fake_hub = FakeHub()
        ws = FakeWebSocket(
            {"type": "send", "target": "linux", "cmd": "uname -a", "who": "agent"}
        )
        with patch.object(app_module, "hub", fake_hub):
            await ws_endpoint(ws)

        self.assertEqual([("linux", "uname -a", "user", None)], fake_hub.calls)

    async def test_websocket_rejects_disallowed_origin(self):
        fake_hub = FakeHub()
        ws = FakeWebSocket(
            {"type": "mode", "mode": "bridge"},
            origin="http://evil.example",
        )
        with patch.object(app_module, "hub", fake_hub):
            await ws_endpoint(ws)

        self.assertEqual([1008], ws.closed)
        self.assertFalse(ws.accepted)
        self.assertEqual([], ws.sent)
        self.assertEqual(set(), fake_hub.clients)
        self.assertEqual([], fake_hub.calls)

    async def test_websocket_accepts_ui_origin_for_operator_mode_change(self):
        fake_hub = FakeHub()
        ws = FakeWebSocket(
            {"type": "mode", "mode": "bridge"},
            origin="http://127.0.0.1:8765",
        )
        with patch.object(app_module, "hub", fake_hub):
            await ws_endpoint(ws)

        self.assertTrue(ws.accepted)
        self.assertEqual([], ws.closed)
        self.assertEqual(
            {"type": "ack", "ok": True, "mode": "bridge"},
            ws.sent[-1],
        )
        self.assertEqual([("mode", "bridge")], fake_hub.calls)

    async def test_websocket_non_loopback_mode_is_rejected_with_token(self):
        fake_hub = FakeHub()
        ws = FakeWebSocket(
            {"type": "mode", "mode": "bridge"},
            host="192.0.2.10",
            authorization="Bearer secret",
        )
        with (
            patch.object(app_module, "hub", fake_hub),
            patch.dict("os.environ", {"SERIAL_BRIDGE_TOKEN": "secret"}, clear=False),
        ):
            await ws_endpoint(ws)

        self.assertEqual(
            {"type": "ack", "ok": False, "error": "Mode changes are loopback-only"},
            ws.sent[-1],
        )
        self.assertEqual([], fake_hub.calls)

    async def test_websocket_loopback_mode_needs_no_token(self):
        fake_hub = FakeHub()
        ws = FakeWebSocket({"type": "mode", "mode": "bridge"})
        with patch.object(app_module, "hub", fake_hub):
            await ws_endpoint(ws)

        self.assertEqual(
            {"type": "ack", "ok": True, "mode": "bridge"},
            ws.sent[-1],
        )
        self.assertEqual([("mode", "bridge")], fake_hub.calls)


class AppHttpAuthorizationTest(unittest.TestCase):
    def setUp(self):
        self.token_temp_dir = tempfile.TemporaryDirectory()
        init_token_store(
            config_path=Path(self.token_temp_dir.name) / "serial_bridge.json",
            environ={},
        )

    def tearDown(self):
        reset_token_store()
        self.token_temp_dir.cleanup()

    def test_loopback_binding_update_persists_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            current = Config(
                slots=[
                    {"name": "linux", "title": "Linux", "com": "COM3", "baud": 115200},
                    {"name": "rtos", "title": "RTOS", "com": "COM6", "baud": 115200},
                ],
                path=config_path,
            )
            client = TestClient(app_module.app, client=("127.0.0.1", 50000))
            with patch.object(app_module, "hub", Hub(current)):
                response = client.post(
                    "/api/bindings",
                    json={
                        "slots": [
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
                    },
                )

            restarted = Hub(load_config(environ={}, config_path=config_path))
            saved = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(200, response.status_code)
        self.assertTrue(response.json()["ok"])
        self.assertEqual("COM8", response.json()["ports"]["linux"]["com"])
        self.assertEqual(57600, restarted.status()["ports"]["linux"]["baud"])
        self.assertEqual("COM9", restarted.status()["ports"]["rtos"]["com"])
        self.assertEqual(230400, restarted.status()["ports"]["rtos"]["baud"])
        self.assertEqual({"live_dir", "slots"}, set(saved.keys()))

    def test_binding_update_persists_live_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            old_live = Path(temp_dir) / "old-live"
            new_live = Path(temp_dir) / "new-live"
            current = Config(
                slots=[
                    {"name": "linux", "title": "Linux", "com": "COM3", "baud": 115200},
                    {"name": "rtos", "title": "RTOS", "com": "COM6", "baud": 115200},
                ],
                path=config_path,
                live_dir=old_live,
            )
            client = TestClient(app_module.app, client=("127.0.0.1", 50000))
            with patch.object(app_module, "hub", Hub(current)):
                response = client.post(
                    "/api/bindings",
                    json=_binding_slots(live_dir=str(new_live)),
                )

            restarted = Hub(load_config(environ={}, config_path=config_path))
            saved = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(200, response.status_code)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(str(new_live.resolve()), response.json()["live_dir"])
        self.assertEqual(str(new_live.resolve()), restarted.status()["live_dir"])
        self.assertEqual(str(new_live.resolve()), saved["live_dir"])

    def test_binding_update_rejects_invalid_live_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            live_dir = Path(temp_dir) / "keep-me"
            live_dir.mkdir()
            current = Config(
                slots=[
                    {"name": "linux", "title": "Linux", "com": "COM3", "baud": 115200},
                    {"name": "rtos", "title": "RTOS", "com": "COM6", "baud": 115200},
                ],
                path=config_path,
                live_dir=live_dir,
            )
            blocker = Path(temp_dir) / "not-a-dir"
            blocker.write_text("x", encoding="utf-8")
            active_hub = Hub(current)
            client = TestClient(app_module.app, client=("127.0.0.1", 50000))
            with patch.object(app_module, "hub", active_hub):
                response = client.post(
                    "/api/bindings",
                    json=_binding_slots(live_dir=str(blocker)),
                )

            saved_exists = config_path.is_file()
            saved_live = None
            if saved_exists:
                saved_live = json.loads(config_path.read_text(encoding="utf-8")).get(
                    "live_dir"
                )

        self.assertEqual(200, response.status_code)
        self.assertFalse(response.json()["ok"])
        self.assertIn("Live Directory", response.json()["error"])
        self.assertEqual(str(live_dir.resolve()), active_hub.status()["live_dir"])
        self.assertFalse(saved_exists)
        self.assertIsNone(saved_live)

    def test_binding_update_rejects_live_dir_change_in_bridge_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            old_live = Path(temp_dir) / "old-live"
            new_live = Path(temp_dir) / "new-live"
            active_hub = Hub(
                Config(
                    slots=[
                        {"name": "linux", "title": "Linux", "com": "COM3", "baud": 115200},
                        {"name": "rtos", "title": "RTOS", "com": "COM6", "baud": 115200},
                    ],
                    path=config_path,
                    live_dir=old_live,
                )
            )
            active_hub.mode = "bridge"
            client = TestClient(app_module.app, client=("127.0.0.1", 50000))
            with patch.object(app_module, "hub", active_hub):
                response = client.post(
                    "/api/bindings",
                    json=_binding_slots(live_dir=str(new_live)),
                )

        self.assertEqual(200, response.status_code)
        self.assertFalse(response.json()["ok"])
        self.assertIn("Live Directory", response.json()["error"])
        self.assertEqual(str(old_live.resolve()), active_hub.status()["live_dir"])
        self.assertFalse(config_path.exists())

    def test_binding_update_is_rejected_while_bridge_mode_owns_ports(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            active_hub = Hub(
                Config(
                    slots=[
                        {"name": "linux", "title": "Linux", "com": "COM3", "baud": 115200},
                        {"name": "rtos", "title": "RTOS", "com": "COM6", "baud": 115200},
                    ],
                    path=config_path,
                )
            )
            active_hub.mode = "bridge"
            client = TestClient(app_module.app, client=("127.0.0.1", 50000))
            with patch.object(app_module, "hub", active_hub):
                response = client.post(
                    "/api/bindings",
                    json={
                        "slots": [
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
                    },
                )

            self.assertFalse(config_path.exists())

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {
                "ok": False,
                "error": "Port Bindings can only be changed in CRT Mode",
            },
            response.json(),
        )
        self.assertEqual("COM3", active_hub.status()["ports"]["linux"]["com"])

    def test_non_loopback_binding_update_is_rejected_before_validation(self):
        client = TestClient(app_module.app, client=("192.0.2.10", 50000))

        response = client.post("/api/bindings", json={})

        self.assertEqual(403, response.status_code)

    def test_binding_update_requires_both_slots(self):
        client = TestClient(app_module.app, client=("127.0.0.1", 50000))

        response = client.post(
            "/api/bindings",
            json={
                "slots": [
                    {
                        "name": "linux",
                        "title": "Linux",
                        "com": "COM8",
                        "baud": 57600,
                    }
                ]
            },
        )

        self.assertEqual(422, response.status_code)

    def test_binding_update_rejects_uppercase_target_name(self):
        client = TestClient(app_module.app, client=("127.0.0.1", 50000))

        response = client.post(
            "/api/bindings",
            json={
                "slots": [
                    {
                        "name": "Linux",
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
            },
        )

        self.assertEqual(422, response.status_code)

    def test_non_loopback_malformed_send_is_rejected_before_validation(self):
        client = TestClient(app_module.app, client=("192.0.2.10", 50000))
        with patch.dict(
            "os.environ", {"SERIAL_BRIDGE_TOKEN": "secret"}, clear=False
        ):
            response = client.post("/api/send", json={})

        self.assertEqual(401, response.status_code)
        self.assertEqual("Bearer", response.headers["www-authenticate"])

    def test_non_loopback_malformed_mode_is_rejected_before_validation(self):
        client = TestClient(app_module.app, client=("192.0.2.10", 50000))
        response = client.post("/api/mode", json={})

        self.assertEqual(403, response.status_code)

    def test_non_loopback_send_without_token_returns_401(self):
        fake_hub = FakeHub()
        client = TestClient(app_module.app, client=("192.0.2.10", 50000))
        with (
            patch.object(app_module, "hub", fake_hub),
            patch.dict("os.environ", {"SERIAL_BRIDGE_TOKEN": "secret"}, clear=False),
        ):
            response = client.post(
                "/api/send",
                json={"target": "linux", "cmd": "uname -a"},
            )

        self.assertEqual(401, response.status_code)
        self.assertEqual("Bearer", response.headers["www-authenticate"])
        self.assertEqual([], fake_hub.calls)

    def test_non_loopback_send_with_wrong_token_returns_401(self):
        fake_hub = FakeHub()
        client = TestClient(app_module.app, client=("192.0.2.10", 50000))
        with (
            patch.object(app_module, "hub", fake_hub),
            patch.dict("os.environ", {"SERIAL_BRIDGE_TOKEN": "secret"}, clear=False),
        ):
            response = client.post(
                "/api/send",
                json={"target": "linux", "cmd": "uname -a"},
                headers={"Authorization": "Bearer wrong"},
            )

        self.assertEqual(401, response.status_code)
        self.assertEqual([], fake_hub.calls)

    def test_loopback_send_needs_no_token(self):
        fake_hub = FakeHub()
        client = TestClient(app_module.app, client=("127.0.0.1", 50000))
        with patch.object(app_module, "hub", fake_hub):
            response = client.post(
                "/api/send",
                json={"target": "linux", "cmd": "uname -a"},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {"ok": True, "target": "linux", "cmd": "uname -a", "who": "user"},
            response.json(),
        )
        self.assertEqual([("linux", "uname -a", "user", None)], fake_hub.calls)

    def test_http_send_derives_who_from_token_instead_of_body(self):
        fake_hub = FakeHub()
        client = TestClient(app_module.app, client=("192.0.2.10", 50000))
        with (
            patch.object(app_module, "hub", fake_hub),
            patch.dict("os.environ", {"SERIAL_BRIDGE_TOKEN": "secret"}, clear=False),
        ):
            response = client.post(
                "/api/send",
                json={"target": "linux", "cmd": "uname -a", "who": "user"},
                headers={"Authorization": "Bearer secret"},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual([("linux", "uname -a", "agent", None)], fake_hub.calls)

    def test_non_loopback_mode_is_rejected_even_with_token(self):
        fake_hub = FakeHub()
        client = TestClient(app_module.app, client=("192.0.2.10", 50000))
        with (
            patch.object(app_module, "hub", fake_hub),
            patch.dict("os.environ", {"SERIAL_BRIDGE_TOKEN": "secret"}, clear=False),
        ):
            response = client.post(
                "/api/mode",
                json={"mode": "bridge"},
                headers={"Authorization": "Bearer secret"},
            )

        self.assertEqual(403, response.status_code)
        self.assertEqual([], fake_hub.calls)

    def test_loopback_mode_needs_no_token(self):
        fake_hub = FakeHub()
        client = TestClient(app_module.app, client=("::1", 50000))
        with patch.object(app_module, "hub", fake_hub):
            response = client.post("/api/mode", json={"mode": "bridge"})

        self.assertEqual(200, response.status_code)
        self.assertEqual({"ok": True, "mode": "bridge"}, response.json())
        self.assertEqual([("mode", "bridge")], fake_hub.calls)

    def test_loopback_port_scan_lists_detected_ports(self):
        detected = [{"com": "COM3", "label": "USB Serial Device"}]
        client = TestClient(app_module.app, client=("127.0.0.1", 50000))
        with patch.object(bridge_operator, "available_ports", return_value=detected):
            response = client.get("/api/ports")

        self.assertEqual(200, response.status_code)
        self.assertEqual({"ok": True, "ports": detected}, response.json())

    def test_non_loopback_port_scan_is_rejected(self):
        client = TestClient(app_module.app, client=("192.0.2.10", 50000))
        with (
            patch.object(bridge_operator, "available_ports", return_value=[]) as scan,
            patch.dict("os.environ", {"SERIAL_BRIDGE_TOKEN": "secret"}, clear=False),
        ):
            response = client.get(
                "/api/ports", headers={"Authorization": "Bearer secret"}
            )

        self.assertEqual(403, response.status_code)
        scan.assert_not_called()

    def test_api_tail_delegates_to_hub_get_tail(self):
        fake_hub = FakeHub()
        fake_hub.get_tail = Mock(
            return_value={"linux": "tail line", "rtos": ""}
        )
        client = TestClient(app_module.app, client=("127.0.0.1", 50000))
        with patch.object(app_module, "hub", fake_hub):
            response = client.get("/api/tail?target=linux&n=10")

        self.assertEqual(200, response.status_code)
        fake_hub.get_tail.assert_called_once_with("linux", 10)
        self.assertEqual(
            {"ok": True, "lines": {"linux": "tail line", "rtos": ""}},
            response.json(),
        )

    def test_tail_returns_empty_lines_when_log_is_none(self):
        fake_hub = FakeHub()
        fake_hub.ports = {
            "linux": {"log": None},
            "rtos": {"log": None},
        }
        client = TestClient(app_module.app, client=("127.0.0.1", 50000))
        with patch.object(app_module, "hub", fake_hub):
            response = client.get("/api/tail")

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual({"linux": "", "rtos": ""}, payload["lines"])


if __name__ == "__main__":
    unittest.main()
