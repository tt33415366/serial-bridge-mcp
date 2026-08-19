"""Load and merge Target Slots (name, title, Port Binding)."""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

PACKAGE_DIR = Path(__file__).resolve().parent
APP_DIR = PACKAGE_DIR.parent
DEFAULT_CONFIG_PATH = APP_DIR / "serial_bridge.json"
DEFAULT_LIVE_DIR = APP_DIR / "live"
SLOT_COUNT = 2
DEFAULT_SLOTS: list[dict[str, str | int]] = [
    {"name": "linux", "title": "Linux", "com": "COM3", "baud": 115200},
    {"name": "rtos", "title": "RTOS", "com": "COM6", "baud": 115200},
]
LEGACY_PORT_KEYS = ("linux", "rtos")
TARGET_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

_ENV_SLOT_NAMES = (
    {
        "com": "SERIAL_BRIDGE_SLOT0_PORT",
        "baud": "SERIAL_BRIDGE_SLOT0_BAUD",
    },
    {
        "com": "SERIAL_BRIDGE_SLOT1_PORT",
        "baud": "SERIAL_BRIDGE_SLOT1_BAUD",
    },
)
_ENV_ALIASES = (
    {
        "com": "SERIAL_BRIDGE_LINUX_PORT",
        "baud": "SERIAL_BRIDGE_LINUX_BAUD",
    },
    {
        "com": "SERIAL_BRIDGE_RTOS_PORT",
        "baud": "SERIAL_BRIDGE_RTOS_BAUD",
    },
)


@dataclass
class Config:
    slots: list[dict[str, str | int]]
    path: Path
    live_dir: Path = DEFAULT_LIVE_DIR
    warning: str | None = None


@dataclass(frozen=True)
class SlotDecision:
    allowed: bool
    title_only: bool
    live_dir: Path | None = None
    error: str | None = None


class SlotPolicy:
    def __init__(self, config: Config):
        self._config = config

    def decide(
        self,
        slots: list[Mapping[str, object]],
        *,
        live_dir: str | None,
        mode: str,
        has_workers: bool,
    ) -> SlotDecision:
        title_only = self._title_only(slots)
        new_live_dir: Path | None = None
        if live_dir is not None:
            try:
                new_live_dir = validate_live_dir(live_dir)
            except ValueError as exc:
                return SlotDecision(
                    False,
                    title_only,
                    error=f"Invalid Live Directory: {exc}",
                )

        live_dir_changing = (
            new_live_dir is not None
            and new_live_dir.resolve() != self._config.live_dir.resolve()
        )
        bindings_locked = mode != "crt" or has_workers
        if live_dir_changing and bindings_locked:
            return SlotDecision(
                False,
                title_only,
                error="Live Directory can only be changed in CRT Mode",
            )
        if bindings_locked and not title_only:
            return SlotDecision(
                False,
                title_only,
                error="Port Bindings can only be changed in CRT Mode",
            )
        return SlotDecision(True, title_only, live_dir=new_live_dir)

    def _title_only(self, slots: list[Mapping[str, object]]) -> bool:
        if len(slots) != len(self._config.slots):
            return False
        for index, incoming in enumerate(slots):
            current = self._config.slots[index]
            for field in ("name", "com", "baud"):
                if str(incoming.get(field, current[field])) != str(current[field]):
                    return False
        return True


def _validated_com(value: object, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source} must be a non-empty string")
    return value.strip()


def _validated_baud(value: object, source: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{source} must be a positive integer")
    return value


def _validated_name(value: object, source: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{source} must be a string")
    name = value.strip().lower()
    if not TARGET_NAME_RE.fullmatch(name):
        raise ValueError(f"{source} must match ^[a-z][a-z0-9_]{{0,31}}$")
    return name


def _validated_title(value: object, source: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{source} must be a string")
    title = value.strip()
    if not 1 <= len(title) <= 64:
        raise ValueError(f"{source} must be 1–64 characters after trim")
    return title


def _default_title_for_name(name: str) -> str:
    return "RTOS" if name == "rtos" else name.replace("_", " ").title()


def _partial_slot(
    index: int,
    values: Mapping[str, object],
    *,
    source_prefix: str,
) -> dict[str, str | int]:
    slot: dict[str, str | int] = {}
    if "name" in values:
        slot["name"] = _validated_name(values["name"], f"{source_prefix}.name")
    if "title" in values:
        slot["title"] = _validated_title(values["title"], f"{source_prefix}.title")
    if "com" in values:
        slot["com"] = _validated_com(values["com"], f"{source_prefix}.com")
    if "baud" in values:
        slot["baud"] = _validated_baud(values["baud"], f"{source_prefix}.baud")
    return slot


def _slot_from_partial(
    index: int,
    values: Mapping[str, object],
    *,
    source_prefix: str,
    defaults: Mapping[str, object] | None = None,
) -> dict[str, str | int]:
    base = dict(defaults or DEFAULT_SLOTS[index])
    merged = dict(base)
    merged.update(_partial_slot(index, values, source_prefix=source_prefix))
    return {
        "name": str(merged["name"]),
        "title": str(merged["title"]),
        "com": str(merged["com"]),
        "baud": int(merged["baud"]),
    }


def _legacy_ports_to_slots(data: Mapping[str, object]) -> list[dict[str, str | int]]:
    ports = data.get("ports")
    if not isinstance(ports, dict):
        raise ValueError("top-level 'ports' object is required")

    slots: list[dict[str, str | int]] = []
    for index, key in enumerate(LEGACY_PORT_KEYS):
        values = ports.get(key, {})
        if not isinstance(values, dict):
            raise ValueError(f"ports.{key} must be an object")
        partial = _partial_slot(
            index,
            values,
            source_prefix=f"ports.{key}",
        )
        if "name" not in partial:
            partial["name"] = key
        if "title" not in partial:
            partial["title"] = _default_title_for_name(key)
        slots.append(partial)
    return slots


def _resolve_live_dir(value: str, source: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source} must be a non-empty string")
    path = Path(value.strip())
    if not path.is_absolute():
        path = APP_DIR / path
    return path.resolve()


def validate_live_dir(value: str) -> Path:
    """Validate an Operator-supplied Live Directory before persisting."""
    path = _resolve_live_dir(value, "live_dir")
    if path.exists() and not path.is_dir():
        raise ValueError("path exists but is not a directory")
    return path


def _parse_saved_live_dir(data: Mapping[str, object]) -> Path | None:
    if "live_dir" not in data:
        return None
    value = data["live_dir"]
    if not isinstance(value, str):
        raise ValueError("live_dir must be a string")
    return _resolve_live_dir(value, "live_dir")


def _assert_unique_target_names(slots: list[dict[str, str | int]]) -> None:
    names = [slot["name"] for slot in slots]
    if len(set(names)) != len(names):
        raise ValueError("Target Names must be unique across slots")


def _parse_saved_slots(data: object) -> list[dict[str, str | int]]:
    """Load persisted config; partial slot fields merge over env/defaults."""
    if not isinstance(data, dict):
        raise ValueError("config must be a JSON object")

    if "slots" in data:
        raw_slots = data["slots"]
        if not isinstance(raw_slots, list) or len(raw_slots) != SLOT_COUNT:
            raise ValueError(f"slots must be an array of exactly {SLOT_COUNT} entries")
        slots: list[dict[str, str | int]] = []
        for index, values in enumerate(raw_slots):
            if not isinstance(values, dict):
                raise ValueError(f"slots[{index}] must be an object")
            slots.append(
                _partial_slot(
                    index,
                    values,
                    source_prefix=f"slots[{index}]",
                )
            )
    elif "ports" in data:
        slots = _legacy_ports_to_slots(data)
    else:
        raise ValueError("top-level 'slots' array is required")

    return slots


def _validated_slots(data: object) -> list[dict[str, str | int]]:
    if not isinstance(data, dict):
        raise ValueError("config must be a JSON object")
    if "slots" not in data:
        raise ValueError("top-level 'slots' array is required")

    raw_slots = data["slots"]
    if not isinstance(raw_slots, list) or len(raw_slots) != SLOT_COUNT:
        raise ValueError(f"slots must be an array of exactly {SLOT_COUNT} entries")

    slots: list[dict[str, str | int]] = []
    for index, values in enumerate(raw_slots):
        if not isinstance(values, dict):
            raise ValueError(f"slots[{index}] must be an object")
        slots.append(
            _slot_from_partial(
                index,
                values,
                source_prefix=f"slots[{index}]",
            )
        )

    _assert_unique_target_names(slots)

    for index, slot in enumerate(slots):
        if "com" not in slot or "baud" not in slot:
            raise ValueError(f"slots[{index}] must include com and baud")

    return slots


def persist_slots(
    config: Config,
    slots: list[Mapping[str, object]],
) -> list[dict[str, str | int]]:
    """Validate and save complete Target Slots to the configured path."""
    validated = _validated_slots({"slots": list(slots)})

    config.path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=config.path.parent,
            prefix=f".{config.path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(
                json.dumps(
                    {
                        "live_dir": str(config.live_dir.resolve()),
                        "slots": validated,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, config.path)
    except BaseException:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise
    return validated


def _apply_env_live_dir(live_dir: Path, env: Mapping[str, str]) -> Path:
    if "SERIAL_BRIDGE_LIVE_DIR" in env:
        return _resolve_live_dir(env["SERIAL_BRIDGE_LIVE_DIR"], "SERIAL_BRIDGE_LIVE_DIR")
    return live_dir


def _apply_cli_live_dir(live_dir: Path, cli_live_dir: Path | None) -> Path:
    if cli_live_dir is not None:
        return _resolve_live_dir(str(cli_live_dir), "--live-dir")
    return live_dir


def _apply_env_bindings(
    slots: list[dict[str, str | int]],
    env: Mapping[str, str],
) -> None:
    for index in range(SLOT_COUNT):
        for names in (_ENV_SLOT_NAMES[index], _ENV_ALIASES[index]):
            if names["com"] in env:
                slots[index]["com"] = _validated_com(
                    env[names["com"]], names["com"]
                )
            if names["baud"] in env:
                source = names["baud"]
                try:
                    baud = int(env[source])
                except ValueError as exc:
                    raise ValueError(f"{source} must be a positive integer") from exc
                slots[index]["baud"] = _validated_baud(baud, source)


def _apply_cli_bindings(
    slots: list[dict[str, str | int]],
    cli_overrides: Mapping[str, Mapping[str, str | int | None]],
) -> None:
    alias_to_index = {"linux": 0, "rtos": 1, "slot0": 0, "slot1": 1}
    for target, values in cli_overrides.items():
        index = alias_to_index.get(target)
        if index is None:
            continue
        com = values.get("com")
        if com is not None:
            slots[index]["com"] = _validated_com(com, f"--{target}-port")
        baud = values.get("baud")
        if baud is not None:
            slots[index]["baud"] = _validated_baud(baud, f"--{target}-baud")


def load_config(
    *,
    environ: Mapping[str, str] | None = None,
    cli_overrides: Mapping[str, Mapping[str, str | int | None]] | None = None,
    config_path: Path | None = None,
) -> Config:
    """Merge defaults, environment/CLI, then the persisted file."""
    env = os.environ if environ is None else environ
    slots = deepcopy(DEFAULT_SLOTS)
    live_dir = DEFAULT_LIVE_DIR.resolve()

    _apply_env_bindings(slots, env)
    _apply_cli_bindings(slots, cli_overrides or {})
    live_dir = _apply_env_live_dir(live_dir, env)
    if cli_overrides and "live_dir" in cli_overrides:
        live_dir = _apply_cli_live_dir(live_dir, cli_overrides["live_dir"])

    path = config_path or Path(env.get("SERIAL_BRIDGE_CONFIG", DEFAULT_CONFIG_PATH))
    warning = None
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            saved = _parse_saved_slots(raw)
            candidate = deepcopy(slots)
            for index, values in enumerate(saved):
                candidate[index].update(values)
            _assert_unique_target_names(candidate)
            slots = candidate
            try:
                saved_live_dir = _parse_saved_live_dir(raw)
                if saved_live_dir is not None:
                    live_dir = saved_live_dir
            except ValueError as exc:
                warning = f"Could not load config {path}: {exc}"
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            warning = f"Could not load config {path}: {exc}"

    return Config(slots=slots, path=path, live_dir=live_dir, warning=warning)


def load_config_from_args(
    argv: list[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    config_path: Path | None = None,
) -> Config:
    parser = argparse.ArgumentParser(description="Serial Bridge")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--linux-port")
    parser.add_argument("--linux-baud", type=int)
    parser.add_argument("--rtos-port")
    parser.add_argument("--rtos-baud", type=int)
    parser.add_argument("--live-dir", type=Path)
    args = parser.parse_args(argv)
    return load_config(
        environ=environ,
        cli_overrides={
            "linux": {"com": args.linux_port, "baud": args.linux_baud},
            "rtos": {"com": args.rtos_port, "baud": args.rtos_baud},
            "live_dir": args.live_dir,
        },
        config_path=config_path or args.config,
    )
