import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import serial_bridge.config as config_module
from serial_bridge.config import (
    APP_DIR,
    Config,
    DEFAULT_LIVE_DIR,
    DEFAULT_SLOTS,
    load_config,
    load_config_from_args,
    persist_slots,
    validate_live_dir,
)


def _default_slots(**overrides):
    slot_keys = ("slot0", "slot1")
    slots = [dict(slot) for slot in DEFAULT_SLOTS]
    for key, values in overrides.items():
        index = slot_keys.index(key)
        slots[index].update(values)
    return slots


class ConfigTest(unittest.TestCase):
    def test_file_wins_over_cli_environment_and_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            config_path.write_text(
                json.dumps(
                    {
                        "slots": [
                            {
                                "name": "linux",
                                "title": "Linux",
                                "com": "COM30",
                                "baud": 38400,
                            },
                            {
                                "name": "rtos",
                                "title": "RTOS",
                                "com": "COM60",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            env = {
                "SERIAL_BRIDGE_CONFIG": str(config_path),
                "SERIAL_BRIDGE_LINUX_PORT": "COM20",
                "SERIAL_BRIDGE_LINUX_BAUD": "57600",
                "SERIAL_BRIDGE_RTOS_PORT": "COM50",
                "SERIAL_BRIDGE_RTOS_BAUD": "19200",
            }

            config = load_config(
                environ=env,
                cli_overrides={
                    "linux": {"com": "COM25", "baud": 74880},
                    "rtos": {"baud": 9600},
                },
            )

            self.assertEqual("COM30", config.slots[0]["com"])
            self.assertEqual(38400, config.slots[0]["baud"])
            self.assertEqual("COM60", config.slots[1]["com"])
            self.assertEqual(9600, config.slots[1]["baud"])
            self.assertIsNone(config.warning)

    def test_environment_overrides_defaults_without_config_file(self):
        config = load_config(
            environ={
                "SERIAL_BRIDGE_LINUX_PORT": "COM8",
                "SERIAL_BRIDGE_RTOS_BAUD": "230400",
            },
            config_path=Path("missing-test-config.json"),
        )

        self.assertEqual("COM8", config.slots[0]["com"])
        self.assertEqual(115200, config.slots[0]["baud"])
        self.assertEqual("COM6", config.slots[1]["com"])
        self.assertEqual(230400, config.slots[1]["baud"])

    def test_cli_flags_override_environment(self):
        config = load_config_from_args(
            [
                "--linux-port",
                "COM14",
                "--linux-baud",
                "9600",
                "--rtos-port",
                "COM15",
                "--rtos-baud",
                "57600",
            ],
            environ={
                "SERIAL_BRIDGE_LINUX_PORT": "COM12",
                "SERIAL_BRIDGE_RTOS_PORT": "COM13",
            },
            config_path=Path("missing-test-config.json"),
        )

        self.assertEqual("COM14", config.slots[0]["com"])
        self.assertEqual(9600, config.slots[0]["baud"])
        self.assertEqual("COM15", config.slots[1]["com"])
        self.assertEqual(57600, config.slots[1]["baud"])

    def test_corrupt_config_falls_back_to_environment_with_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            config_path.write_text("{not json", encoding="utf-8")

            config = load_config(
                environ={
                    "SERIAL_BRIDGE_CONFIG": str(config_path),
                    "SERIAL_BRIDGE_LINUX_PORT": "COM12",
                }
            )

            self.assertEqual("COM12", config.slots[0]["com"])
            self.assertEqual("COM6", config.slots[1]["com"])
            self.assertIn("Could not load config", config.warning)

    def test_invalid_environment_binding_fails_with_source_name(self):
        invalid_values = (
            ("SERIAL_BRIDGE_LINUX_PORT", ""),
            ("SERIAL_BRIDGE_LINUX_BAUD", "not-a-number"),
            ("SERIAL_BRIDGE_LINUX_BAUD", "-1"),
        )
        for name, value in invalid_values:
            with self.subTest(name=name, value=value):
                with self.assertRaisesRegex(ValueError, name):
                    load_config(
                        environ={name: value},
                        config_path=Path("missing-test-config.json"),
                    )

    def test_invalid_cli_binding_fails_with_flag_name(self):
        invalid_args = (
            ["--linux-port", ""],
            ["--linux-baud", "-1"],
        )
        for args in invalid_args:
            with self.subTest(args=args):
                with self.assertRaisesRegex(ValueError, args[0]):
                    load_config_from_args(
                        args,
                        environ={},
                        config_path=Path("missing-test-config.json"),
                    )

    def test_persist_slots_flushes_same_directory_temp_before_replace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            config = Config(slots=_default_slots(), path=config_path)
            observed = {}
            real_replace = config_module.os.replace

            def inspect_then_replace(source, destination):
                source_path = Path(source)
                observed["source"] = source_path
                observed["destination"] = Path(destination)
                observed["content"] = source_path.read_text(encoding="utf-8")
                real_replace(source, destination)

            with patch.object(config_module.os, "replace", inspect_then_replace):
                persist_slots(
                    config,
                    _default_slots(
                        slot0={"com": "COM8", "baud": 57600},
                        slot1={"com": "COM9", "baud": 230400},
                    ),
                )

            self.assertEqual(config_path.parent, observed["source"].parent)
            self.assertEqual(config_path, observed["destination"])
            saved = json.loads(observed["content"])
            self.assertEqual({"live_dir", "slots"}, set(saved.keys()))
            self.assertEqual("COM8", saved["slots"][0]["com"])
            self.assertEqual(230400, saved["slots"][1]["baud"])
            self.assertFalse(observed["source"].exists())

    def test_slot_env_vars_override_defaults(self):
        config = load_config(
            environ={
                "SERIAL_BRIDGE_SLOT0_PORT": "COM20",
                "SERIAL_BRIDGE_SLOT0_BAUD": "38400",
                "SERIAL_BRIDGE_SLOT1_PORT": "COM21",
                "SERIAL_BRIDGE_SLOT1_BAUD": "57600",
            },
            config_path=Path("missing-test-config.json"),
        )

        self.assertEqual("COM20", config.slots[0]["com"])
        self.assertEqual(38400, config.slots[0]["baud"])
        self.assertEqual("COM21", config.slots[1]["com"])
        self.assertEqual(57600, config.slots[1]["baud"])

    def test_linux_rtos_env_aliases_map_to_slot_indices(self):
        config = load_config(
            environ={
                "SERIAL_BRIDGE_LINUX_PORT": "COM12",
                "SERIAL_BRIDGE_LINUX_BAUD": "9600",
                "SERIAL_BRIDGE_RTOS_PORT": "COM13",
                "SERIAL_BRIDGE_RTOS_BAUD": "230400",
            },
            config_path=Path("missing-test-config.json"),
        )

        self.assertEqual("COM12", config.slots[0]["com"])
        self.assertEqual(9600, config.slots[0]["baud"])
        self.assertEqual("COM13", config.slots[1]["com"])
        self.assertEqual(230400, config.slots[1]["baud"])

    def test_legacy_ports_shape_loads_and_rewrites_to_slots(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            config_path.write_text(
                json.dumps(
                    {
                        "ports": {
                            "linux": {"com": "COM30", "baud": 38400},
                            "rtos": {"com": "COM60", "baud": 57600},
                        }
                    }
                ),
                encoding="utf-8",
            )
            config = load_config(environ={}, config_path=config_path)

            self.assertEqual("linux", config.slots[0]["name"])
            self.assertEqual("Linux", config.slots[0]["title"])
            self.assertEqual("COM30", config.slots[0]["com"])
            self.assertEqual("rtos", config.slots[1]["name"])
            self.assertEqual("RTOS", config.slots[1]["title"])

            persist_slots(config, config.slots)
            saved = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual({"live_dir", "slots"}, set(saved.keys()))
        self.assertEqual("COM60", saved["slots"][1]["com"])

    def test_target_name_validation_and_lowercase_storage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            config = Config(slots=_default_slots(), path=config_path)

            with self.assertRaisesRegex(ValueError, "name"):
                persist_slots(
                    config,
                    _default_slots(slot0={"name": "Bad-Name"}),
                )
            with self.assertRaisesRegex(ValueError, "name"):
                persist_slots(
                    config,
                    _default_slots(slot0={"name": "1linux"}),
                )

            saved = persist_slots(
                config,
                _default_slots(slot0={"name": "Embedded_Linux"}),
            )
            self.assertEqual("embedded_linux", saved[0]["name"])

    def test_target_names_must_be_unique(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            config = Config(slots=_default_slots(), path=config_path)

            with self.assertRaisesRegex(ValueError, "unique"):
                persist_slots(
                    config,
                    _default_slots(slot0={"name": "linux"}, slot1={"name": "linux"}),
                )

    def test_duplicate_target_names_on_load_falls_back_with_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            config_path.write_text(
                json.dumps(
                    {
                        "slots": [
                            {
                                "name": "linux",
                                "title": "Linux",
                                "com": "COM30",
                                "baud": 38400,
                            },
                            {
                                "name": "linux",
                                "title": "RTOS",
                                "com": "COM60",
                                "baud": 57600,
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            config = load_config(
                environ={"SERIAL_BRIDGE_CONFIG": str(config_path)},
            )

            self.assertIn("unique", config.warning.lower())
            self.assertEqual("linux", config.slots[0]["name"])
            self.assertEqual("rtos", config.slots[1]["name"])

    def test_display_title_trim_and_length(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            config = Config(slots=_default_slots(), path=config_path)

            with self.assertRaisesRegex(ValueError, "title"):
                persist_slots(config, _default_slots(slot0={"title": "   "}))
            with self.assertRaisesRegex(ValueError, "title"):
                persist_slots(config, _default_slots(slot0={"title": "x" * 65}))

            saved = persist_slots(
                config,
                _default_slots(slot0={"title": "  My Linux  "}),
            )
            self.assertEqual("My Linux", saved[0]["title"])

    def test_duplicate_display_titles_are_allowed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            config = Config(slots=_default_slots(), path=config_path)

            saved = persist_slots(
                config,
                _default_slots(slot0={"title": "Console"}, slot1={"title": "Console"}),
            )

            self.assertEqual("Console", saved[0]["title"])
            self.assertEqual("Console", saved[1]["title"])

    def test_default_live_dir_is_app_directory_live(self):
        config = load_config(
            environ={},
            config_path=Path("missing-test-config.json"),
        )

        self.assertEqual(DEFAULT_LIVE_DIR.resolve(), config.live_dir.resolve())

    def test_config_file_without_live_dir_keeps_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            config_path.write_text(
                json.dumps(
                    {
                        "slots": [
                            {
                                "name": "linux",
                                "title": "Linux",
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
                    }
                ),
                encoding="utf-8",
            )

            config = load_config(
                environ={"SERIAL_BRIDGE_CONFIG": str(config_path)},
            )

            self.assertEqual(DEFAULT_LIVE_DIR.resolve(), config.live_dir.resolve())
            self.assertNotIn(
                "live_dir", json.loads(config_path.read_text(encoding="utf-8"))
            )

    def test_live_dir_env_overrides_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_dir = Path(temp_dir) / "from-env"
            config = load_config(
                environ={"SERIAL_BRIDGE_LIVE_DIR": str(env_dir)},
                config_path=Path("missing-test-config.json"),
            )

            self.assertEqual(env_dir.resolve(), config.live_dir.resolve())

    def test_live_dir_cli_overrides_env(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_dir = Path(temp_dir) / "from-env"
            cli_dir = Path(temp_dir) / "from-cli"
            config = load_config_from_args(
                ["--live-dir", str(cli_dir)],
                environ={"SERIAL_BRIDGE_LIVE_DIR": str(env_dir)},
                config_path=Path("missing-test-config.json"),
            )

            self.assertEqual(cli_dir.resolve(), config.live_dir.resolve())

    def test_live_dir_file_wins_over_env_and_cli(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            file_dir = Path(temp_dir) / "from-file"
            config_path.write_text(
                json.dumps(
                    {
                        "live_dir": str(file_dir),
                        "slots": [
                            {
                                "name": "linux",
                                "title": "Linux",
                                "com": "COM3",
                                "baud": 115200,
                            },
                            {
                                "name": "rtos",
                                "title": "RTOS",
                                "com": "COM6",
                                "baud": 115200,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            config = load_config_from_args(
                ["--live-dir", str(Path(temp_dir) / "from-cli")],
                environ={
                    "SERIAL_BRIDGE_CONFIG": str(config_path),
                    "SERIAL_BRIDGE_LIVE_DIR": str(Path(temp_dir) / "from-env"),
                },
            )

            self.assertEqual(file_dir.resolve(), config.live_dir.resolve())

    def test_relative_live_dir_resolves_against_app_directory(self):
        config = load_config(
            environ={"SERIAL_BRIDGE_LIVE_DIR": "relative-live"},
            config_path=Path("missing-test-config.json"),
        )

        self.assertEqual((APP_DIR / "relative-live").resolve(), config.live_dir.resolve())

    def test_corrupt_live_dir_in_file_falls_back_with_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            env_dir = Path(temp_dir) / "from-env"
            config_path.write_text(
                json.dumps(
                    {
                        "live_dir": 12345,
                        "slots": [
                            {
                                "name": "linux",
                                "title": "Linux",
                                "com": "COM3",
                                "baud": 115200,
                            },
                            {
                                "name": "rtos",
                                "title": "RTOS",
                                "com": "COM6",
                                "baud": 115200,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            config = load_config(
                environ={
                    "SERIAL_BRIDGE_CONFIG": str(config_path),
                    "SERIAL_BRIDGE_LIVE_DIR": str(env_dir),
                }
            )

            self.assertEqual(env_dir.resolve(), config.live_dir.resolve())
            self.assertIn("live_dir", config.warning.lower())

    def test_persist_slots_includes_live_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            live_dir = Path(temp_dir) / "session-logs"
            config = Config(
                slots=_default_slots(),
                path=config_path,
                live_dir=live_dir,
            )

            persist_slots(config, _default_slots())
            saved = json.loads(config_path.read_text(encoding="utf-8"))

            self.assertEqual(str(live_dir.resolve()), saved["live_dir"])

    def test_validate_live_dir_rejects_empty(self):
        with self.assertRaises(ValueError):
            validate_live_dir("   ")

    def test_validate_live_dir_rejects_existing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "not-a-dir"
            file_path.write_text("x", encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_live_dir(str(file_path))

    def test_validate_live_dir_resolves_relative_against_app_dir(self):
        resolved = validate_live_dir("relative-live")
        self.assertEqual((APP_DIR / "relative-live").resolve(), resolved)

    def test_gitignore_excludes_default_live_directory(self):
        gitignore = (APP_DIR / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("live/", gitignore)

    def test_readme_documents_live_directory(self):
        readme = (APP_DIR / "README.md").read_text(encoding="utf-8")
        self.assertIn("SERIAL_BRIDGE_LIVE_DIR", readme)
        self.assertIn("--live-dir", readme)
        self.assertIn("YYYY-MM-DD-HHMMSS", readme)
        self.assertIn("migrated", readme.lower())


if __name__ == "__main__":
    unittest.main()
