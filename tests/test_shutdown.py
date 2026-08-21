"""Ctrl-C must end the Hub even while Agents hold MCP streams open."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from serial_bridge import app as app_module


class GracefulShutdownTimeoutTest(unittest.TestCase):
    def _run_main(self):
        fake_hub = MagicMock()
        fake_hub.config = SimpleNamespace(
            warning=None,
            path=Path("serial_bridge.json"),
        )
        fake_hub.ports.values.return_value = []
        with (
            patch.object(app_module, "Hub", return_value=fake_hub),
            patch.object(app_module, "load_config_from_args"),
            patch.object(app_module, "init_token_store"),
            patch("uvicorn.run") as run,
        ):
            app_module.main(["--no-open-ui"])
        return run.call_args

    def test_main_bounds_graceful_shutdown(self):
        """An unbounded wait never ends: MCP streams and UI sockets stay open."""
        timeout = self._run_main().kwargs.get("timeout_graceful_shutdown")

        self.assertIsNotNone(timeout)
        self.assertGreater(timeout, 0)

    def test_graceful_shutdown_stays_short_enough_for_ctrl_c(self):
        timeout = self._run_main().kwargs.get("timeout_graceful_shutdown")

        self.assertLessEqual(timeout, 10)


if __name__ == "__main__":
    unittest.main()
