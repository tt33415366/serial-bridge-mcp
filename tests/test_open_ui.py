import io
import unittest
from contextlib import asynccontextmanager, redirect_stdout
from unittest.mock import AsyncMock, MagicMock, patch

import serial_bridge.app as app_module
from serial_bridge.app import (
    CONSOLE_UI_URL,
    open_console_ui,
    parse_startup_args,
    resolve_open_ui,
)


class ResolveOpenUiTest(unittest.TestCase):
    def test_unset_env_defaults_to_open(self):
        self.assertTrue(resolve_open_ui(environ={}))

    def test_disable_values_are_case_insensitive(self):
        for value in ("0", "false", "no", "off", "FALSE", "No", "OFF"):
            with self.subTest(value=value):
                self.assertFalse(
                    resolve_open_ui(environ={"SERIAL_BRIDGE_OPEN_UI": value})
                )

    def test_other_env_values_still_open(self):
        self.assertTrue(resolve_open_ui(environ={"SERIAL_BRIDGE_OPEN_UI": "1"}))
        self.assertTrue(resolve_open_ui(environ={"SERIAL_BRIDGE_OPEN_UI": "yes"}))

    def test_cli_open_ui_overrides_env_disable(self):
        self.assertTrue(
            resolve_open_ui(
                environ={"SERIAL_BRIDGE_OPEN_UI": "off"},
                cli_open_ui=True,
            )
        )

    def test_cli_no_open_ui_overrides_env_enable(self):
        self.assertFalse(
            resolve_open_ui(
                environ={"SERIAL_BRIDGE_OPEN_UI": "yes"},
                cli_open_ui=False,
            )
        )


class ParseStartupArgsTest(unittest.TestCase):
    def test_strips_no_open_ui_flag(self):
        remaining, cli_open_ui = parse_startup_args(["--no-open-ui", "--linux-port", "COM8"])

        self.assertEqual(["--linux-port", "COM8"], remaining)
        self.assertFalse(cli_open_ui)

    def test_strips_open_ui_flag(self):
        remaining, cli_open_ui = parse_startup_args(["--open-ui"])

        self.assertEqual([], remaining)
        self.assertTrue(cli_open_ui)

    def test_no_flag_returns_none(self):
        remaining, cli_open_ui = parse_startup_args(["--config", "x.json"])

        self.assertEqual(["--config", "x.json"], remaining)
        self.assertIsNone(cli_open_ui)


class OpenConsoleUiTest(unittest.TestCase):
    def test_opens_console_root_not_setup(self):
        browser = MagicMock()
        browser.open.return_value = True

        open_console_ui(webbrowser_module=browser)

        browser.open.assert_called_once_with(CONSOLE_UI_URL)

    def test_failed_open_prints_warning(self):
        browser = MagicMock()
        browser.open.return_value = False
        captured = io.StringIO()

        with redirect_stdout(captured):
            open_console_ui(webbrowser_module=browser)

        self.assertIn("WARNING", captured.getvalue())
        self.assertIn(CONSOLE_UI_URL, captured.getvalue())

    def test_exception_prints_warning(self):
        browser = MagicMock()
        browser.open.side_effect = OSError("no browser")
        captured = io.StringIO()

        with redirect_stdout(captured):
            open_console_ui(webbrowser_module=browser)

        self.assertIn("WARNING", captured.getvalue())
        self.assertIn("no browser", captured.getvalue())


class MainOpenUiTest(unittest.TestCase):
    def setUp(self):
        self._previous_flag = app_module._open_ui_on_startup

    def tearDown(self):
        app_module._open_ui_on_startup = self._previous_flag

    def test_main_does_not_open_before_listen(self):
        fake_hub = MagicMock()
        fake_hub.config = MagicMock(warning=None, path=MagicMock())
        fake_hub.ports.values.return_value = []

        with (
            patch.object(app_module, "Hub", return_value=fake_hub),
            patch.object(app_module, "load_config_from_args"),
            patch.object(app_module, "init_token_store"),
            patch.object(app_module, "open_console_ui") as open_ui,
            patch("uvicorn.run"),
        ):
            app_module.main()

        open_ui.assert_not_called()

    def test_main_sets_open_flag_from_env_disable(self):
        fake_hub = MagicMock()
        fake_hub.config = MagicMock(warning=None, path=MagicMock())
        fake_hub.ports.values.return_value = []

        with (
            patch.object(app_module, "Hub", return_value=fake_hub),
            patch.object(app_module, "load_config_from_args"),
            patch.object(app_module, "init_token_store"),
            patch("uvicorn.run"),
            patch.dict("os.environ", {"SERIAL_BRIDGE_OPEN_UI": "off"}, clear=False),
        ):
            app_module.main()

        self.assertFalse(app_module._open_ui_on_startup)

    def test_main_sets_open_flag_from_cli(self):
        fake_hub = MagicMock()
        fake_hub.config = MagicMock(warning=None, path=MagicMock())
        fake_hub.ports.values.return_value = []

        with (
            patch.object(app_module, "Hub", return_value=fake_hub),
            patch.object(app_module, "load_config_from_args"),
            patch.object(app_module, "init_token_store"),
            patch("uvicorn.run"),
        ):
            app_module.main(["--no-open-ui"])

        self.assertFalse(app_module._open_ui_on_startup)


class LifespanOpenUiTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._previous_flag = app_module._open_ui_on_startup

    def tearDown(self):
        app_module._open_ui_on_startup = self._previous_flag

    async def test_lifespan_opens_ui_when_enabled(self):
        app_module._open_ui_on_startup = True

        @asynccontextmanager
        async def fake_run():
            yield

        with (
            patch.object(app_module, "open_console_ui") as open_ui,
            patch.object(app_module.mcp.session_manager, "run", return_value=fake_run()),
        ):
            async with app_module._lifespan(app_module.app):
                pass

        open_ui.assert_called_once()

    async def test_lifespan_skips_ui_when_disabled(self):
        app_module._open_ui_on_startup = False

        @asynccontextmanager
        async def fake_run():
            yield

        with (
            patch.object(app_module, "open_console_ui") as open_ui,
            patch.object(app_module.mcp.session_manager, "run", return_value=fake_run()),
        ):
            async with app_module._lifespan(app_module.app):
                pass

        open_ui.assert_not_called()


if __name__ == "__main__":
    unittest.main()
