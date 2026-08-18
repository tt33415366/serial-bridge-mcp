"""Serial ownership, mode, transcript, and WebSocket broadcast authority."""
from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any, Mapping

from serial import SerialException
from serial_bridge.config import Config, load_config, persist_slots, validate_live_dir
from serial_bridge.hub.queue import exec_result
from serial_bridge.hub.text import sanitize_display, strip_ansi, ts


class Hub:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or load_config()
        self.ports: dict[str, dict[str, Any]] = {}
        for slot in self.config.slots:
            self._register_slot(slot)
        self.mode = "crt"  # crt | bridge — start released so we can open on demand
        self.clients: set[Any] = set()
        self.lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._transition_lock = threading.RLock()
        self.workers: dict[str, Any] = {}
        self.loop: asyncio.AbstractEventLoop | None = None

    def _register_slot(self, slot: Mapping[str, str | int]) -> None:
        name = str(slot["name"])
        self.ports[name] = {
            "name": name,
            "title": str(slot["title"]),
            "com": str(slot["com"]),
            "baud": int(slot["baud"]),
            "log": None,
        }

    def _session_log_path(self, name: str, session_time) -> Path:
        stamp = session_time.strftime("%Y-%m-%d-%H%M%S")
        return self.config.live_dir / f"{name}-{stamp}.log"

    def _assign_session_logs(self, session_time=None) -> None:
        import serial_bridge.hub as hub

        session_time = session_time or hub.datetime.now()
        for name in self.ports:
            path = self._session_log_path(name, session_time)
            self.ports[name]["log"] = path
            path.touch(exist_ok=True)

    def _write_bridge_status(self) -> None:
        live_dir = self.config.live_dir
        if not live_dir.is_dir():
            return
        (live_dir / "bridge_status.json").write_text(
            json.dumps(self.status(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _title_only_change(self, slots: list[Mapping[str, object]]) -> bool:
        if len(slots) != len(self.config.slots):
            return False
        for index, incoming in enumerate(slots):
            current = self.config.slots[index]
            for field in ("name", "com", "baud"):
                if str(incoming.get(field, current[field])) != str(current[field]):
                    return False
        return True

    def _apply_slot_updates(self, slots: list[dict[str, str | int]]) -> None:
        new_ports: dict[str, dict[str, Any]] = {}
        for index, slot in enumerate(slots):
            old_name = str(self.config.slots[index]["name"])
            new_name = str(slot["name"])
            if old_name in self.ports and old_name == new_name:
                entry = dict(self.ports[old_name])
            else:
                entry = {"log": None}
            entry.update(
                {
                    "name": new_name,
                    "title": str(slot["title"]),
                    "com": str(slot["com"]),
                    "baud": int(slot["baud"]),
                }
            )
            new_ports[new_name] = entry
        self.ports = new_ports
        self.config.slots = slots
        self.config.warning = None

    def _unknown_target_error(self, target: str) -> str:
        known = ", ".join(sorted(self.ports))
        return f"unknown target {target!r}; known targets: {known}"

    def resolve_target(self, target: object) -> tuple[str | None, str | None]:
        if not isinstance(target, str):
            return None, "target must be a Target Name string"
        target_name = target.strip().lower()
        if target_name not in self.ports:
            return target_name, self._unknown_target_error(target_name)
        return target_name, None

    def _unknown_target_exec(self, target: str) -> dict[str, Any]:
        return exec_result(
            target,
            ok=False,
            error=self._unknown_target_error(target),
        )

    async def broadcast(self, msg: dict[str, Any]) -> None:
        dead: list[Any] = []
        data = json.dumps(msg, ensure_ascii=False)
        for ws in list(self.clients):
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    def emit(self, msg: dict[str, Any]) -> None:
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast(msg), self.loop)

    def append_log(self, target: str, direction: str, text: str, who: str = "") -> None:
        import serial_bridge.hub as hub

        cfg = self.ports[target]
        log_path = cfg.get("log")
        if log_path is None:
            raise RuntimeError(f"no session log assigned for target {target!r}")
        line = (
            f"{hub.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} "
            f"{direction} [{cfg['title'].upper()}]"
        )
        if who:
            line += f" ({who})"
        line += f" {strip_ansi(text).rstrip()}\n"
        with self.lock:
            with log_path.open("a", encoding="utf-8", errors="replace") as f:
                f.write(line)
        self.emit(
            {
                "type": "line",
                "target": target,
                "direction": direction,
                "who": who,
                "text": sanitize_display(text).rstrip(),
                "ts": ts(),
            }
        )

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            mode = self.mode
            workers = dict(self.workers)
        status = {
            "mode": mode,
            "live_dir": str(self.config.live_dir.resolve()),
            "ports": {
                k: {
                    "name": v["name"],
                    "title": v["title"],
                    "com": v["com"],
                    "baud": v["baud"],
                    "open": k in workers and workers[k].is_open,
                    "busy": k in workers and workers[k].is_busy,
                    "log": str(v["log"]) if v.get("log") else "",
                }
                for k, v in self.ports.items()
            },
        }
        if self.config.warning:
            status["config_warning"] = self.config.warning
        return status

    def get_tail(self, target: str = "both", n: int = 80) -> dict[str, str]:
        out: dict[str, str] = {}
        keys = list(self.ports) if target == "both" else [target]
        for key in keys:
            if key not in self.ports:
                continue
            log_path = self.ports[key].get("log")
            if log_path and log_path.is_file():
                lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                out[key] = "\n".join(lines[-n:])
            else:
                out[key] = ""
        return out

    def update_slots(
        self,
        slots: list[dict[str, str | int | object]],
        live_dir: str | None = None,
    ) -> dict[str, Any]:
        with self._transition_lock:
            with self._state_lock:
                title_only = self._title_only_change(slots)
                new_live_dir: Path | None = None
                if live_dir is not None:
                    try:
                        new_live_dir = validate_live_dir(live_dir)
                    except ValueError as exc:
                        return {"ok": False, "error": f"Invalid Live Directory: {exc}"}

                live_dir_changing = (
                    new_live_dir is not None
                    and new_live_dir.resolve() != self.config.live_dir.resolve()
                )
                if live_dir_changing and (self.mode != "crt" or self.workers):
                    return {
                        "ok": False,
                        "error": "Live Directory can only be changed in CRT Mode",
                    }
                if (self.mode != "crt" or self.workers) and not title_only:
                    return {
                        "ok": False,
                        "error": "Port Bindings can only be changed in CRT Mode",
                    }

                old_live_dir = self.config.live_dir
                try:
                    if new_live_dir is not None:
                        self.config.live_dir = new_live_dir
                    validated = persist_slots(self.config, slots)
                except (OSError, UnicodeError, ValueError) as exc:
                    self.config.live_dir = old_live_dir
                    return {"ok": False, "error": f"Could not save Port Bindings: {exc}"}

                self._apply_slot_updates(validated)

        status = self.status()
        self.emit({"type": "status", **status})
        return {"ok": True, **status}

    def update_bindings(
        self, ports: dict[str, dict[str, str | int]]
    ) -> dict[str, Any]:
        """Backward-compatible wrapper for tests and callers keyed by target name."""
        slots = []
        for index, current in enumerate(self.config.slots):
            name = str(current["name"])
            binding = ports.get(name, {})
            slots.append(
                {
                    "name": name,
                    "title": current["title"],
                    "com": binding.get("com", current["com"]),
                    "baud": binding.get("baud", current["baud"]),
                }
            )
        return self.update_slots(slots)

    def start_bridge(self) -> dict[str, Any]:
        import serial_bridge.hub as hub

        with self._transition_lock:
            with self._state_lock:
                if self.mode == "bridge" and all(
                    k in self.workers and self.workers[k].is_open for k in self.ports
                ):
                    return {"ok": True, "mode": "bridge", "msg": "Already in Bridge Mode"}
            errors: list[str] = []
            self.stop_bridge(quiet=True)
            try:
                self.config.live_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                self.emit(
                    {
                        "type": "status",
                        **self.status(),
                        "error": f"Could not create Live Directory: {exc}",
                    }
                )
                return {
                    "ok": False,
                    "mode": "crt",
                    "error": f"Could not create Live Directory: {exc}",
                }
            self._assign_session_logs()
            for key, cfg in self.ports.items():
                w = hub.PortWorker(key, cfg["com"], cfg["baud"], self)
                try:
                    w.open()
                    w.start()
                    with self._state_lock:
                        self.workers[key] = w
                except SerialException as e:
                    errors.append(f"{cfg['com']}: {e}")
            if errors:
                self.stop_bridge(quiet=True)
                self.emit({"type": "status", **self.status(), "error": "; ".join(errors)})
                return {
                    "ok": False,
                    "mode": "crt",
                    "error": (
                        "Failed to open serial ports "
                        "(confirm SecureCRT has disconnected the configured ports): "
                        + "; ".join(errors)
                    ),
                }
            with self._state_lock:
                self.mode = "bridge"
            self.emit({"type": "status", **self.status()})
            self.emit(
                {
                    "type": "system",
                    "text": "Entered Bridge Mode: Agent and Operator share both streams below",
                }
            )
            self._write_bridge_status()
            return {"ok": True, "mode": "bridge"}

    def stop_bridge(self, quiet: bool = False) -> dict[str, Any]:
        with self._transition_lock:
            with self._state_lock:
                self.mode = "crt"
                workers = list(self.workers.values())
                for w in workers:
                    w.abort_agent_work()
                self.workers.clear()
            for w in workers:
                w.close()
            if not quiet:
                self.emit({"type": "status", **self.status()})
                ports = "/".join(str(cfg["com"]) for cfg in self.ports.values())
                self.emit(
                    {
                        "type": "system",
                        "text": (
                            f"Switched to CRT Mode: ports released; "
                            f"SecureCRT can connect to {ports}"
                        ),
                    }
                )
            self._write_bridge_status()
            return {"ok": True, "mode": "crt"}

    def send(
        self,
        target: object,
        cmd: str = "",
        who: str = "user",
        raw_hex: str | None = None,
    ) -> dict[str, Any]:
        target_name, error = self.resolve_target(target)
        if error is not None:
            return {"ok": False, "error": error}
        assert target_name is not None
        target = target_name
        with self._state_lock:
            if self.mode != "bridge":
                return {
                    "ok": False,
                    "error": "CRT Mode is active; switch to Bridge Mode before Send",
                }
            worker = self.workers.get(target)
            if worker is None or not worker.is_open:
                return {"ok": False, "error": f"{target} port is not open"}
            raw = None
            if raw_hex is not None:
                if cmd:
                    return {
                        "ok": False,
                        "error": "cmd and raw_hex are mutually exclusive",
                    }
                try:
                    raw = bytes.fromhex(raw_hex)
                except ValueError:
                    return {"ok": False, "error": "raw_hex must be valid hexadecimal"}
                if not raw:
                    return {"ok": False, "error": "raw_hex must contain at least one byte"}
            worker.send(cmd, who=who, raw=raw)
        result = {"ok": True, "target": target, "cmd": cmd, "who": who}
        if raw_hex is not None:
            result["raw_hex"] = raw.hex()
        return result

    def exec(
        self,
        target: object,
        cmd: str,
        prompt: str | None = None,
        prompt_is_regex: bool = False,
    ) -> dict[str, Any]:
        target_name, error = self.resolve_target(target)
        if error is not None:
            if target_name is not None:
                return self._unknown_target_exec(target_name)
            return exec_result("", ok=False, error=error)
        assert target_name is not None
        target = target_name
        with self._state_lock:
            if self.mode != "bridge":
                return exec_result(
                    target,
                    ok=False,
                    error="CRT Mode is active; switch to Bridge Mode before Exec",
                )
            worker = self.workers.get(target)
            if worker is None or not worker.is_open or worker._stop.is_set():
                return exec_result(
                    target,
                    ok=False,
                    error=f"{target} port is not open",
                )
            request = worker.enqueue_exec(
                cmd,
                prompt=prompt,
                prompt_is_regex=prompt_is_regex,
            )
        return worker.wait_exec(request)
