import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import serial_bridge.app as app_module
from conftest import BlockingExecHub, FakeHub
from fastapi.testclient import TestClient
from serial_bridge.config import Config
from serial_bridge.hub import Hub
from serial_bridge.token_store import init_token_store, reset_token_store


MCP_HEADERS = {
    "Authorization": "Bearer secret",
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def call_tool(client, name, arguments=None, headers=None):
    return client.post(
        "/mcp",
        headers=headers if headers is not None else MCP_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        },
    )


class McpHttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.token_temp_dir = tempfile.TemporaryDirectory()
        cls.env_patch = patch.dict(
            "os.environ",
            {"SERIAL_BRIDGE_TOKEN": "secret"},
            clear=False,
        )
        cls.env_patch.start()
        init_token_store(
            config_path=Path(cls.token_temp_dir.name) / "serial_bridge.json",
            environ={"SERIAL_BRIDGE_TOKEN": "secret"},
        )
        cls.client_context = TestClient(app_module.app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        reset_token_store()
        cls.token_temp_dir.cleanup()
        cls.env_patch.stop()

    def test_mcp_tools_live_in_mcp_server_module(self):
        import serial_bridge.mcp_server as mcp_server

        self.assertTrue(callable(mcp_server.serial_status))
        self.assertTrue(callable(mcp_server.serial_exec))
        self.assertTrue(callable(mcp_server.serial_send))
        self.assertTrue(callable(mcp_server.create_mcp))
        self.assertTrue(callable(mcp_server.mount_mcp))

    def test_mcp_requires_bearer_even_on_loopback(self):
        missing = call_tool(self.client, "serial_status", headers={})
        wrong = call_tool(
            self.client,
            "serial_status",
            headers={**MCP_HEADERS, "Authorization": "Bearer wrong"},
        )

        self.assertEqual(401, missing.status_code)
        self.assertEqual("Bearer", missing.headers["www-authenticate"])
        self.assertEqual(401, wrong.status_code)

    def test_mcp_exposes_send_status_and_exec_tools(self):
        response = self.client.post(
            "/mcp",
            headers=MCP_HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            },
        )

        self.assertEqual(
            {"serial_exec", "serial_send", "serial_status"},
            {tool["name"] for tool in response.json()["result"]["tools"]},
        )

    def test_mcp_has_no_port_binding_write_capability(self):
        response = self.client.post(
            "/mcp",
            headers=MCP_HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            },
        )

        tools = response.json()["result"]["tools"]
        self.assertFalse(
            any(
                "binding" in tool["name"] or "ports" in tool["inputSchema"].get("properties", {})
                for tool in tools
            )
        )

    def test_main_binds_existing_port_for_lan_agents(self):
        fake_hub = FakeHub()
        fake_hub.config = SimpleNamespace(
            warning=None,
            path=Path("serial_bridge.json"),
        )
        with (
            patch.object(app_module, "Hub", return_value=fake_hub),
            patch.object(app_module, "load_config_from_args"),
            patch.object(app_module, "init_token_store") as init_token,
            patch("uvicorn.run") as run,
        ):
            app_module.main()

        init_token.assert_called_once_with(config_path=fake_hub.config.path)
        run.assert_called_once_with(
            app_module.app,
            host="0.0.0.0",
            port=8765,
            log_level="info",
        )

    def test_serial_status_returns_bindings_open_and_busy_hints(self):
        fake_hub = FakeHub()
        with patch.object(app_module, "hub", fake_hub):
            response = call_tool(self.client, "serial_status")

        self.assertEqual(200, response.status_code)
        self.assertEqual(fake_hub.status(), response.json()["result"]["structuredContent"])

    def test_serial_exec_delegates_to_hub_and_returns_designed_fields(self):
        fake_hub = FakeHub()
        with patch.object(app_module, "hub", fake_hub):
            response = call_tool(
                self.client,
                "serial_exec",
                {
                    "target": "linux",
                    "cmd": "uname -a",
                    "prompt": r"\$ $",
                    "prompt_is_regex": True,
                },
            )

        result = response.json()["result"]["structuredContent"]
        self.assertEqual(
            {
                "ok": True,
                "target": "linux",
                "output": "Linux\n",
                "truncated": False,
                "timed_out": False,
                "aborted": False,
            },
            result,
        )
        self.assertEqual(
            [("linux", "uname -a", r"\$ $", True)],
            fake_hub.calls,
        )

    def test_serial_exec_in_crt_mode_requires_bridge_mode(self):
        config = Config(
            slots=[
                {"name": "linux", "title": "Linux", "com": "COM8", "baud": 57600},
                {"name": "rtos", "title": "RTOS", "com": "COM9", "baud": 115200},
            ],
            path=Path("serial_bridge.json"),
        )
        crt_hub = Hub(config)
        with patch.object(app_module, "hub", crt_hub):
            response = call_tool(
                self.client,
                "serial_exec",
                {"target": "linux", "cmd": "uname -a"},
            )

        result = response.json()["result"]["structuredContent"]
        self.assertFalse(result["ok"])
        self.assertFalse(result["timed_out"])
        self.assertFalse(result["aborted"])
        self.assertIn("Bridge Mode", result["error"])

    def test_serial_send_delegates_text_line_without_waiting_for_output(self):
        fake_hub = FakeHub()
        with patch.object(app_module, "hub", fake_hub):
            response = call_tool(
                self.client,
                "serial_send",
                {"target": "linux", "cmd": "reboot"},
            )

        result = response.json()["result"]["structuredContent"]
        self.assertTrue(result["ok"])
        self.assertEqual(
            [("linux", "reboot", "agent", None)],
            fake_hub.calls,
        )

    def test_serial_send_delegates_raw_hex(self):
        fake_hub = FakeHub()
        with patch.object(app_module, "hub", fake_hub):
            response = call_tool(
                self.client,
                "serial_send",
                {"target": "rtos", "raw_hex": "03"},
            )

        result = response.json()["result"]["structuredContent"]
        self.assertTrue(result["ok"])
        self.assertEqual(
            [("rtos", "", "agent", "03")],
            fake_hub.calls,
        )

    def test_serial_send_in_crt_mode_requires_bridge_mode(self):
        config = Config(
            slots=[
                {"name": "linux", "title": "Linux", "com": "COM8", "baud": 57600},
                {"name": "rtos", "title": "RTOS", "com": "COM6", "baud": 115200},
            ],
            path=Path("serial_bridge.json"),
        )
        crt_hub = Hub(config)
        with patch.object(app_module, "hub", crt_hub):
            response = call_tool(
                self.client,
                "serial_send",
                {"target": "linux", "cmd": "reboot"},
            )

        result = response.json()["result"]["structuredContent"]
        self.assertFalse(result["ok"])
        self.assertIn("Bridge Mode", result["error"])

    def test_serial_status_includes_name_and_title(self):
        fake_hub = FakeHub()
        with patch.object(app_module, "hub", fake_hub):
            response = call_tool(self.client, "serial_status")

        linux = response.json()["result"]["structuredContent"]["ports"]["linux"]
        self.assertEqual("linux", linux["name"])
        self.assertEqual("Linux", linux["title"])

    def test_mcp_serial_exec_normalizes_mixed_case_target_name(self):
        fake_hub = FakeHub()
        with patch.object(app_module, "hub", fake_hub):
            response = call_tool(
                self.client,
                "serial_exec",
                {"target": "Linux", "cmd": "uname -a"},
            )

        result = response.json()["result"]["structuredContent"]
        self.assertTrue(result["ok"])
        self.assertEqual("linux", result["target"])
        self.assertEqual([("linux", "uname -a", None, False)], fake_hub.calls)

    def test_mcp_serial_send_normalizes_mixed_case_target_name(self):
        fake_hub = FakeHub()
        with patch.object(app_module, "hub", fake_hub):
            response = call_tool(
                self.client,
                "serial_send",
                {"target": "RTOS", "cmd": "reboot"},
            )

        result = response.json()["result"]["structuredContent"]
        self.assertTrue(result["ok"])
        self.assertEqual("rtos", result["target"])
        self.assertEqual([("rtos", "reboot", "agent", None)], fake_hub.calls)

    def test_mcp_unknown_target_matches_http_error_shape(self):
        fake_hub = FakeHub()
        client = TestClient(app_module.app, client=("127.0.0.1", 50000))
        with patch.object(app_module, "hub", fake_hub):
            http = client.post(
                "/api/send",
                json={"target": "Missing", "cmd": "help"},
            )
            mcp = call_tool(
                self.client,
                "serial_send",
                {"target": "Missing", "cmd": "help"},
            )

        http_error = http.json()["error"]
        mcp_error = mcp.json()["result"]["structuredContent"]["error"]
        self.assertIn("unknown target 'missing'", http_error)
        self.assertEqual(http_error, mcp_error)
        self.assertEqual([], fake_hub.calls)

    def test_mcp_targets_use_renamed_target_name(self):
        config = Config(
            slots=[
                {"name": "embedded", "title": "Embedded", "com": "COM8", "baud": 57600},
                {"name": "rtos", "title": "RTOS", "com": "COM9", "baud": 115200},
            ],
            path=Path("serial_bridge.json"),
        )
        renamed_hub = Hub(config)
        with patch.object(app_module, "hub", renamed_hub):
            missing = call_tool(
                self.client,
                "serial_exec",
                {"target": "linux", "cmd": "uname -a"},
            )
            ok = call_tool(
                self.client,
                "serial_exec",
                {"target": "embedded", "cmd": "uname -a"},
            )

        missing_result = missing.json()["result"]["structuredContent"]
        ok_result = ok.json()["result"]["structuredContent"]
        self.assertFalse(missing_result["ok"])
        self.assertIn("unknown target", missing_result["error"])
        self.assertFalse(ok_result["ok"])
        self.assertIn("Bridge Mode", ok_result["error"])


class EventLoopResponsivenessTest(unittest.IsolatedAsyncioTestCase):
    async def test_mode_and_status_respond_while_exec_is_in_flight(self):
        blocking = BlockingExecHub()
        with patch.object(app_module, "hub", blocking):
            in_flight = asyncio.create_task(app_module.serial_exec("linux", "reboot"))
            self.assertTrue(await asyncio.to_thread(blocking.exec_started.wait, 5))
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app_module.app),
                base_url="http://127.0.0.1:8765",
            ) as client:
                started = time.monotonic()
                mode = await client.post("/api/mode", json={"mode": "crt"})
                status = await client.get("/api/status")
                elapsed = time.monotonic() - started
            blocking.release_exec.set()
            result = await asyncio.wait_for(in_flight, 5)

        self.assertEqual({"ok": True, "mode": "crt"}, mode.json())
        self.assertEqual(200, status.status_code)
        self.assertLess(elapsed, 1.0)
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
