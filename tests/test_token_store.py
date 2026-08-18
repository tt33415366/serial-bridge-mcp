import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import serial_bridge.token_store as token_store_module
from serial_bridge.config import persist_slots, load_config
from serial_bridge.token_store import (
    DEFAULT_TOKEN_FILENAME,
    init_token_store,
    load_or_create_token_store,
    reset_token_store,
    resolve_token_path,
    rotate_access_token,
    valid_bearer_token,
)


class TokenStoreTest(unittest.TestCase):
    def tearDown(self) -> None:
        reset_token_store()

    def test_resolve_token_path_default_beside_config(self) -> None:
        config_path = Path("/data/serial_bridge.json")
        self.assertEqual(
            Path("/data/serial_bridge.token"),
            resolve_token_path(config_path, {}),
        )

    def test_resolve_token_path_honors_serial_bridge_token_file(self) -> None:
        config_path = Path("/data/serial_bridge.json")
        env = {"SERIAL_BRIDGE_TOKEN_FILE": "/secrets/hub.token"}
        self.assertEqual(
            Path("/secrets/hub.token"),
            resolve_token_path(config_path, env),
        )

    def test_first_boot_generates_secrets_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            token_path = config_path.with_name(DEFAULT_TOKEN_FILENAME)

            with (
                patch.dict("os.environ", {}, clear=True),
                patch(
                    "serial_bridge.token_store.secrets.token_urlsafe", return_value="generated-token"
                ),
            ):
                store = load_or_create_token_store(
                    config_path=config_path,
                    environ={},
                )

            self.assertEqual("generated-token", store.file_token)
            self.assertTrue(token_path.is_file())
            self.assertEqual("generated-token", token_path.read_text(encoding="utf-8"))

    def test_restart_loads_same_token_without_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            token_path = config_path.with_name(DEFAULT_TOKEN_FILENAME)
            token_path.write_text("persisted-token\n", encoding="utf-8")

            with patch.dict("os.environ", {}, clear=True):
                first = load_or_create_token_store(config_path=config_path, environ={})
                second = load_or_create_token_store(config_path=config_path, environ={})

            self.assertEqual("persisted-token", first.file_token)
            self.assertEqual(first.file_token, second.file_token)

    def test_env_overrides_file_for_runtime_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            token_path = config_path.with_name(DEFAULT_TOKEN_FILENAME)
            token_path.write_text("file-token\n", encoding="utf-8")

            with patch.dict(
                "os.environ",
                {"SERIAL_BRIDGE_TOKEN": "override-token"},
                clear=True,
            ):
                store = load_or_create_token_store(
                    config_path=config_path,
                    environ={"SERIAL_BRIDGE_TOKEN": "override-token"},
                )

                self.assertEqual("file-token", store.file_token)
                self.assertEqual("override-token", store.token)

    def test_env_mirrored_into_secrets_file_on_first_boot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            token_path = config_path.with_name(DEFAULT_TOKEN_FILENAME)

            with patch.dict(
                "os.environ",
                {"SERIAL_BRIDGE_TOKEN": "env-boot-token"},
                clear=True,
            ):
                store = load_or_create_token_store(
                    config_path=config_path,
                    environ={"SERIAL_BRIDGE_TOKEN": "env-boot-token"},
                )

                self.assertEqual("env-boot-token", store.file_token)
                self.assertEqual("env-boot-token", store.token)
                self.assertTrue(token_path.is_file())
                self.assertEqual(
                    "env-boot-token", token_path.read_text(encoding="utf-8").strip()
                )

    def test_env_does_not_rewrite_existing_secrets_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            token_path = config_path.with_name(DEFAULT_TOKEN_FILENAME)
            token_path.write_text("existing-file-token\n", encoding="utf-8")

            with patch.dict(
                "os.environ",
                {"SERIAL_BRIDGE_TOKEN": "different-env"},
                clear=True,
            ):
                store = load_or_create_token_store(
                    config_path=config_path,
                    environ={"SERIAL_BRIDGE_TOKEN": "different-env"},
                )

                self.assertEqual("existing-file-token", store.file_token)
                self.assertEqual("different-env", store.token)
                self.assertEqual(
                    "existing-file-token",
                    token_path.read_text(encoding="utf-8").strip(),
                )

    def test_valid_bearer_accepts_matching_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            with patch.dict(
                "os.environ",
                {"SERIAL_BRIDGE_TOKEN": "secret"},
                clear=True,
            ):
                store = load_or_create_token_store(
                    config_path=config_path,
                    environ={"SERIAL_BRIDGE_TOKEN": "secret"},
                )

                self.assertTrue(store.valid_bearer("Bearer secret"))
                self.assertFalse(store.valid_bearer("Bearer wrong"))
                self.assertFalse(store.valid_bearer(None))

    def test_valid_bearer_uses_file_token_when_env_unset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            token_path = config_path.with_name(DEFAULT_TOKEN_FILENAME)
            token_path.write_text("file-only-token\n", encoding="utf-8")

            with patch.dict("os.environ", {}, clear=True):
                reset_token_store()
                init_token_store(config_path=config_path, environ={})
                self.assertTrue(valid_bearer_token("Bearer file-only-token"))
                self.assertFalse(valid_bearer_token("Bearer wrong"))

                reset_token_store()
                init_token_store(config_path=config_path, environ={})
                self.assertTrue(valid_bearer_token("Bearer file-only-token"))

    def test_port_binding_json_never_contains_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            config = load_config(config_path=config_path, environ={})
            with (
                patch.dict("os.environ", {}, clear=True),
                patch(
                    "serial_bridge.token_store.secrets.token_urlsafe", return_value="must-not-leak"
                ),
            ):
                load_or_create_token_store(config_path=config.path, environ={})

            persist_slots(
                config,
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
                        "baud": 115200,
                    },
                ],
            )

            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual({"live_dir", "slots"}, set(saved.keys()))
            self.assertNotIn("must-not-leak", config_path.read_text(encoding="utf-8"))

    def test_init_token_store_registers_global_store(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            token_path = config_path.with_name(DEFAULT_TOKEN_FILENAME)
            token_path.write_text("global-token\n", encoding="utf-8")

            with patch.dict("os.environ", {}, clear=True):
                store = init_token_store(config_path=config_path, environ={})

            self.assertIs(store, token_store_module.get_token_store())
            self.assertEqual("global-token", store.file_token)

    def test_rotate_rewrites_secrets_file_and_updates_store(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            token_path = config_path.with_name(DEFAULT_TOKEN_FILENAME)
            token_path.write_text("before-rotate\n", encoding="utf-8")

            with (
                patch.dict("os.environ", {}, clear=True),
                patch(
                    "serial_bridge.token_store.secrets.token_urlsafe", return_value="after-rotate"
                ),
            ):
                init_token_store(config_path=config_path, environ={})
                new_token, env_override = rotate_access_token()

            self.assertEqual("after-rotate", new_token)
            self.assertFalse(env_override)
            self.assertEqual("after-rotate", token_path.read_text(encoding="utf-8"))
            self.assertEqual(
                "after-rotate", token_store_module.get_token_store().file_token
            )

    def test_rotate_reports_env_override(self) -> None:
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
                patch(
                    "serial_bridge.token_store.secrets.token_urlsafe", return_value="rotated-on-disk"
                ),
            ):
                init_token_store(
                    config_path=config_path,
                    environ={"SERIAL_BRIDGE_TOKEN": "env-token"},
                )
                _, env_override = rotate_access_token()

                self.assertTrue(env_override)
                self.assertEqual(
                    "rotated-on-disk", token_path.read_text(encoding="utf-8").strip()
                )
                self.assertEqual(
                    "env-token", token_store_module.get_token_store().token
                )


if __name__ == "__main__":
    unittest.main()
