import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import serial_bridge.app as app_module
import serial_bridge.setup as bridge_setup
from fastapi.testclient import TestClient
from serial_bridge.token_store import (
    DEFAULT_TOKEN_FILENAME,
    get_token_store,
    init_token_store,
    reset_token_store,
)

MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


class SetupPageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.token_temp_dir = tempfile.TemporaryDirectory()
        init_token_store(
            config_path=Path(self.token_temp_dir.name) / "serial_bridge.json",
            environ={},
        )

    def tearDown(self) -> None:
        reset_token_store()
        self.token_temp_dir.cleanup()

    def test_setup_helpers_live_in_bridge_setup(self):
        self.assertTrue(callable(bridge_setup.detect_lan_ip))
        self.assertTrue(callable(bridge_setup.setup_payload))
        self.assertTrue(callable(bridge_setup.register_setup_routes))
        self.assertFalse(hasattr(app_module, "detect_lan_ip"))
        self.assertFalse(hasattr(app_module, "_setup_payload"))

    def test_get_setup_returns_html_without_colliding_with_mcp(self):
        loopback = TestClient(app_module.app, client=("127.0.0.1", 50000))
        non_loopback = TestClient(app_module.app, client=("192.0.2.10", 50000))

        setup = loopback.get("/setup")
        mcp = loopback.post("/mcp", headers=MCP_HEADERS, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

        self.assertEqual(200, setup.status_code)
        self.assertIn("text/html", setup.headers["content-type"])
        self.assertNotEqual(setup.status_code, mcp.status_code)

        remote_setup = non_loopback.get("/setup")
        self.assertEqual(200, remote_setup.status_code)
        self.assertIn("text/html", remote_setup.headers["content-type"])

    def test_index_links_to_setup(self):
        response = TestClient(app_module.app).get("/")
        self.assertEqual(200, response.status_code)
        self.assertIn("/setup", response.text)

    def test_setup_static_js_contains_no_token_placeholder(self):
        setup_js = (app_module.STATIC / "setup.js").read_text(encoding="utf-8")
        self.assertNotIn("Bearer ", setup_js)

    def test_loopback_setup_api_shows_token_and_snippet(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            token_path = config_path.with_name(DEFAULT_TOKEN_FILENAME)
            token_path.write_text("loopback-token\n", encoding="utf-8")
            with (
                patch.dict("os.environ", {}, clear=True),
                patch.object(bridge_setup, "detect_lan_ip", return_value="192.168.1.42"),
            ):
                init_token_store(config_path=config_path, environ={})
                client = TestClient(app_module.app, client=("127.0.0.1", 50000))
                response = client.get("/api/setup")

        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertTrue(body["loopback"])
        self.assertEqual("loopback-token", body["token"])
        self.assertIn("192.168.1.42", body["hub_url"])
        snippet = json.loads(body["cursor_snippet"])
        server = snippet["mcpServers"]["serial-bridge"]
        self.assertEqual("http://192.168.1.42:8765/mcp", server["url"])
        self.assertEqual("Bearer loopback-token", server["headers"]["Authorization"])

    def test_loopback_setup_api_falls_back_to_localhost_when_no_lan_ip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            token_path = config_path.with_name(DEFAULT_TOKEN_FILENAME)
            token_path.write_text("local-token\n", encoding="utf-8")
            with (
                patch.dict("os.environ", {}, clear=True),
                patch.object(bridge_setup, "detect_lan_ip", return_value=None),
            ):
                init_token_store(config_path=config_path, environ={})
                client = TestClient(app_module.app, client=("127.0.0.1", 50000))
                response = client.get("/api/setup")

        body = response.json()
        self.assertIn("127.0.0.1", body["hub_url"])
        snippet = json.loads(body["cursor_snippet"])
        self.assertIn("127.0.0.1", snippet["mcpServers"]["serial-bridge"]["url"])

    def test_non_loopback_setup_api_hides_secrets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            token_path = config_path.with_name(DEFAULT_TOKEN_FILENAME)
            token_path.write_text("remote-hidden-token\n", encoding="utf-8")
            with (
                patch.dict("os.environ", {}, clear=True),
                patch.object(bridge_setup, "detect_lan_ip", return_value="192.168.1.42"),
            ):
                init_token_store(config_path=config_path, environ={})
                client = TestClient(app_module.app, client=("192.0.2.10", 50000))
                response = client.get("/api/setup")

        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertFalse(body["loopback"])
        self.assertNotIn("token", body)
        self.assertNotIn("cursor_snippet", body)
        self.assertNotIn("remote-hidden-token", response.text)
        self.assertIn("192.168.1.42", body["hub_url"])

    def test_non_loopback_rotate_is_rejected(self):
        client = TestClient(app_module.app, client=("192.0.2.10", 50000))
        response = client.post("/api/setup/rotate")
        self.assertEqual(403, response.status_code)

    def test_loopback_rotate_rewrites_secrets_file_without_env(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            token_path = config_path.with_name(DEFAULT_TOKEN_FILENAME)
            token_path.write_text("old-token\n", encoding="utf-8")
            with (
                patch.dict("os.environ", {}, clear=True),
                patch(
                    "serial_bridge.token_store.secrets.token_urlsafe",
                    side_effect=["new-token", "unused"],
                ),
            ):
                init_token_store(config_path=config_path, environ={})
                client = TestClient(app_module.app, client=("127.0.0.1", 50000))
                response = client.post("/api/setup/rotate")

                self.assertEqual(200, response.status_code)
                body = response.json()
                self.assertEqual("new-token", body["token"])
                self.assertFalse(body["env_override"])
                self.assertEqual(
                    "new-token", token_path.read_text(encoding="utf-8").strip()
                )

    def test_loopback_rotate_warns_when_env_overrides(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            token_path = config_path.with_name(DEFAULT_TOKEN_FILENAME)
            token_path.write_text("file-token\n", encoding="utf-8")
            with (
                patch.dict(
                    "os.environ",
                    {"SERIAL_BRIDGE_TOKEN": "env-token"},
                    clear=True,
                ),
                patch("serial_bridge.token_store.secrets.token_urlsafe", return_value="rotated-file-token"),
            ):
                init_token_store(
                    config_path=config_path,
                    environ={"SERIAL_BRIDGE_TOKEN": "env-token"},
                )
                client = TestClient(app_module.app, client=("127.0.0.1", 50000))
                response = client.post("/api/setup/rotate")

                body = response.json()
                self.assertTrue(body["env_override"])
                self.assertIn("env", body["warning"].lower())
                self.assertEqual("env-token", body["token"])
                self.assertIn("env-token", body["cursor_snippet"])
                self.assertNotIn("rotated-file-token", body["cursor_snippet"])
                self.assertEqual(
                    "rotated-file-token", token_path.read_text(encoding="utf-8").strip()
                )

    def test_rotate_without_env_updates_mcp_auth(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            token_path = config_path.with_name(DEFAULT_TOKEN_FILENAME)
            token_path.write_text("old-token\n", encoding="utf-8")
            with (
                patch.dict("os.environ", {}, clear=True),
                patch(
                    "serial_bridge.token_store.secrets.token_urlsafe",
                    side_effect=["new-token", "unused"],
                ),
            ):
                init_token_store(config_path=config_path, environ={})
                client = TestClient(app_module.app, client=("127.0.0.1", 50000))
                self.assertTrue(get_token_store().valid_bearer("Bearer old-token"))
                rotate_response = client.post("/api/setup/rotate")
                self.assertTrue(get_token_store().valid_bearer("Bearer new-token"))
                self.assertFalse(get_token_store().valid_bearer("Bearer old-token"))

                self.assertEqual(200, rotate_response.status_code)


if __name__ == "__main__":
    unittest.main()
