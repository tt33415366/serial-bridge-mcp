"""Serial ownership, mode, transcript, and WebSocket broadcast authority."""
from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any, Mapping

from serial_bridge.config import Config, SlotPolicy, load_config, persist_slots
from serial_bridge.hub.mode_transition import ModeTransition
from serial_bridge.hub.queue import exec_result
from serial_bridge.hub.trace import AgentTrace
from serial_bridge.hub.transcript import Transcript


class Hub:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or load_config()
        self._slot_policy = SlotPolicy(self.config)
        self.ports: dict[str, dict[str, Any]] = {}
        for slot in self.config.slots:
            self._register_slot(slot)
        self.mode = "crt"  # crt | bridge — start released so we can open on demand
        self.clients: set[Any] = set()
        self._agent_trace = AgentTrace(lambda event: self.emit(event))
        import serial_bridge.hub as hub

        self._transcript = Transcript(
            lambda: self.ports,
            lambda: self.config.live_dir,
            lambda event: self.emit(event),
            lambda: hub.datetime.now(),
        )
        self._state_lock = threading.Lock()
        self._transition_lock = threading.RLock()
        self.workers: dict[str, Any] = {}
        self._mode_transition = ModeTransition(
            self,
            self._transcript,
            lambda name, port, baud: hub.PortWorker(name, port, baud, self),
        )
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
        return self._transcript.session_log_path(name, session_time)

    def _assign_session_logs(self, session_time=None) -> None:
        self._transcript.assign_session_logs(session_time)

    def _write_bridge_status(self) -> None:
        self._mode_transition.write_bridge_status()

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

    def record_exec_start(self, target: str, cmd: str, prompt: str | None) -> int:
        return self._agent_trace.record_start(target, cmd, prompt)

    def record_exec_end(
        self,
        id: int,
        target: str,
        ended_by: str,
        ms: int,
        bytes: int,
        truncated: bool,
        ok: bool,
    ) -> None:
        self._agent_trace.record_end(
            id,
            target,
            ended_by,
            ms,
            bytes,
            truncated,
            ok,
        )

    def get_agent_log(self) -> list[dict[str, Any]]:
        return self._agent_trace.get_agent_log()

    def append_log(self, target: str, direction: str, text: str, who: str = "") -> None:
        self._transcript.append_log(target, direction, text, who)

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
        return self._transcript.get_tail(target, n)

    def update_slots(
        self,
        slots: list[dict[str, str | int | object]],
        live_dir: str | None = None,
    ) -> dict[str, Any]:
        with self._transition_lock:
            with self._state_lock:
                decision = self._slot_policy.decide(
                    slots,
                    live_dir=live_dir,
                    mode=self.mode,
                    has_workers=bool(self.workers),
                )
                if not decision.allowed:
                    return {"ok": False, "error": decision.error}

                old_live_dir = self.config.live_dir
                try:
                    if decision.live_dir is not None:
                        self.config.live_dir = decision.live_dir
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
        return self._mode_transition.start_bridge()

    def stop_bridge(self, quiet: bool = False) -> dict[str, Any]:
        return self._mode_transition.stop_bridge(quiet)

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
