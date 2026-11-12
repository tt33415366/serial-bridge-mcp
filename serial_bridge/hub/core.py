"""Serial ownership, mode, transcript, and WebSocket broadcast authority."""
from __future__ import annotations

import asyncio
import json
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from serial_bridge.config import (
    MAX_SLOT_COUNT,
    Config,
    SlotPolicy,
    load_config,
    persist_slots,
    unused_default_slot,
)
from serial_bridge.constants import SESSION_LOG_ROUTE, TAIL_DEFAULT_N
from serial_bridge.hub.coalesce import LineCoalescer
from serial_bridge.hub.mode_transition import ModeTransition
from serial_bridge.hub.queue import ExecSpec, exec_result
from serial_bridge.hub.readiness import ShellReadiness
from serial_bridge.hub.trace import AgentTrace, payload_bytes
from serial_bridge.hub.transcript import Transcript, tail_response


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
        self._readiness = ShellReadiness()
        self._mode_switch_allowed = False
        self._switching = False
        self.workers: dict[str, Any] = {}
        self.open_errors: dict[str, str] = {}
        self._mode_transition = ModeTransition(
            self,
            self._transcript,
            lambda name, port, baud: hub.PortWorker(name, port, baud, self),
        )
        self.loop: asyncio.AbstractEventLoop | None = None
        self._line_coalescer = LineCoalescer(self._dispatch)

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
            new_name = str(slot["name"])
            old_name = (
                str(self.config.slots[index]["name"])
                if index < len(self.config.slots)
                else None
            )
            if new_name in self.ports:
                entry = dict(self.ports[new_name])
            elif old_name is not None and old_name in self.ports and old_name == new_name:
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
        self._line_coalescer.emit(msg)

    def _dispatch(self, msg: dict[str, Any]) -> None:
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
        returned_bytes: int = 0,
    ) -> None:
        self._agent_trace.record_end(
            id,
            target,
            ended_by,
            ms,
            bytes,
            truncated,
            ok,
            returned_bytes,
        )

    def record_agent_read(
        self,
        kind: str,
        result: dict[str, Any],
        *,
        target: str | None = None,
        **fields: Any,
    ) -> None:
        """Trace a Tail or status read served to an Agent (MCP layer calls this).

        Exec and Send are traced inside the Hub because ``who`` identifies the
        Agent there; status and Tail reads are shared with the Operator UI, so
        only the MCP tools report them.
        """
        self._agent_trace.record_read(
            kind,
            target=target,
            ok=bool(result["ok"]) if "ok" in result else True,
            returned_bytes=payload_bytes(result),
            **fields,
        )

    def get_agent_log(self) -> list[dict[str, Any]]:
        return self._agent_trace.get_agent_log()

    @property
    def returned_total(self) -> int:
        return self._agent_trace.returned_total

    def append_log(self, target: str, direction: str, text: str, who: str = "") -> None:
        self._transcript.append_log(target, direction, text, who)

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            mode = self.mode
            workers = dict(self.workers)
            open_errors = dict(self.open_errors)
            mode_switch = self._mode_switch_info(workers, self._mode_switch_allowed)
        shell = {
            k: self._readiness.evaluate(k, self.config.target_prompts.get(k))
            for k in self.ports
        }
        status = {
            "mode": mode,
            "mode_switch": mode_switch,
            "live_dir": str(self.config.live_dir.resolve()),
            "ports": {
                k: {
                    "name": v["name"],
                    "title": v["title"],
                    "com": v["com"],
                    "baud": v["baud"],
                    "open": k in workers and workers[k].is_open,
                    "busy": k in workers and workers[k].is_busy,
                    "port_state": self._port_state(k, workers),
                    "target_prompt": self.config.target_prompts.get(k, ""),
                    "shell": shell[k][0],
                    "shell_observed_at": shell[k][1],
                    "log": str(v["log"]) if v.get("log") else "",
                    "log_url": (
                        f"{SESSION_LOG_ROUTE}?target={k}" if v.get("log") else ""
                    ),
                }
                for k, v in self.ports.items()
            },
        }
        for k, message in open_errors.items():
            if k in status["ports"]:
                status["ports"][k]["open_error"] = message
        if self.config.warning:
            status["config_warning"] = self.config.warning
        if len(self.config.slots) < MAX_SLOT_COUNT:
            status["add_defaults"] = unused_default_slot(self.config.slots)
        return status

    @staticmethod
    def _mode_switch_info(workers: dict[str, Any], allowed: bool) -> dict[str, Any]:
        busy_targets = sorted(k for k, w in workers.items() if w.is_busy)
        if not allowed:
            next_action = "ask_operator_to_enable_mode_switch"
        elif busy_targets:
            next_action = "wait_for_exec_to_finish"
        else:
            next_action = "call serial_set_mode"
        return {
            "allowed": allowed,
            "busy": bool(busy_targets),
            "busy_targets": busy_targets,
            "next_action": next_action,
        }

    def set_mode_switch_permission(self, allowed: bool) -> dict[str, Any]:
        with self._state_lock:
            self._mode_switch_allowed = bool(allowed)
        status = self.status()
        self.emit({"type": "status", **status})
        return {"ok": True, **status}

    def set_mode_agent(self, mode: object) -> dict[str, Any]:
        requested = mode.lower().strip() if isinstance(mode, str) else ""
        if requested not in ("bridge", "crt"):
            return {"ok": False, "error": "mode must be bridge or crt"}
        with self._transition_lock:
            with self._state_lock:
                info = self._mode_switch_info(
                    dict(self.workers), self._mode_switch_allowed
                )
                if not info["allowed"]:
                    return {
                        "ok": False,
                        "error": "Mode switching by Agents is not permitted",
                        "mode_switch": info,
                    }
                if info["busy"]:
                    return {
                        "ok": False,
                        "error": "Exec in flight; mode not changed",
                        "busy_targets": info["busy_targets"],
                        "mode_switch": info,
                    }
                self._switching = True
            try:
                return self.start_bridge() if requested == "bridge" else self.stop_bridge()
            finally:
                with self._state_lock:
                    self._switching = False

    @staticmethod
    def _port_state(key: str, workers: dict[str, Any]) -> str:
        worker = workers.get(key)
        if worker is None:
            return "closed"
        if getattr(worker, "lost", False):
            return "lost"
        return "open" if worker.is_open else "closed"

    def get_tail(self, target: str = "both", n: int = 80) -> dict[str, str]:
        return self._transcript.get_tail(target, n)

    def tail(
        self,
        target: str,
        n: int = TAIL_DEFAULT_N,
        with_timestamps: bool = False,
    ) -> dict[str, Any]:
        return tail_response(
            target,
            n,
            with_timestamps,
            resolve=self.resolve_target,
            session_log=lambda name: self.ports[name].get("log"),
            read_tail=lambda name, count: self.get_tail(target=name, n=count)[name],
        )

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

    def observe_rx(self, target: str, chunk: bytes) -> None:
        self._readiness.observe(
            target,
            chunk.decode("utf-8", errors="replace"),
            datetime.now().astimezone().isoformat(timespec="milliseconds"),
        )

    def clear_readiness(self, target: str) -> None:
        self._readiness.clear(target)

    def clear_all_readiness(self) -> None:
        self._readiness.clear()

    def set_target_prompt(self, target: object, pattern: object) -> dict[str, Any]:
        """Operator-only: set or clear (empty string) a Target's Target Prompt."""
        target_name, error = self.resolve_target(target)
        if error is not None:
            return {"ok": False, "error": error}
        if not isinstance(pattern, str):
            return {"ok": False, "error": "pattern must be a string"}
        if pattern:
            try:
                re.compile(pattern)
            except re.error as exc:
                return {"ok": False, "error": f"pattern is not a valid regex: {exc}"}
        with self._transition_lock:
            with self._state_lock:
                previous = self.config.target_prompts
                updated = dict(previous)
                if pattern:
                    updated[target_name] = pattern
                else:
                    updated.pop(target_name, None)
                self.config.target_prompts = updated
                try:
                    persist_slots(self.config, self.config.slots)
                except (OSError, UnicodeError, ValueError) as exc:
                    self.config.target_prompts = previous
                    return {"ok": False, "error": f"Could not save Target Prompt: {exc}"}
            self.clear_readiness(target_name)
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

    def port_lost(self, target: str) -> None:
        """A worker's port dropped: tell clients; Bridge Mode and ports stay as they are."""
        self._readiness.clear(target)
        self.emit({"type": "status", **self.status()})
        try:
            self._mode_transition.write_bridge_status()
        except OSError:
            pass  # runs on the worker thread; the status file is best-effort here

    def send(
        self,
        target: object,
        cmd: str = "",
        who: str = "user",
        raw_hex: str | None = None,
    ) -> dict[str, Any]:
        result = self._send(target, cmd, who, raw_hex)
        if who == "agent":
            self._agent_trace.record_read(
                "send",
                target=result.get("target") or (target if isinstance(target, str) else None),
                ok=bool(result["ok"]),
                returned_bytes=payload_bytes(result),
                cmd=cmd if raw_hex is None else f"[raw] {raw_hex}",
            )
        return result

    def _send(
        self,
        target: object,
        cmd: str,
        who: str,
        raw_hex: str | None,
    ) -> dict[str, Any]:
        target_name, error = self.resolve_target(target)
        if error is not None:
            return {"ok": False, "error": error}
        assert target_name is not None
        target = target_name
        with self._state_lock:
            if self._switching:
                return {"ok": False, "error": "mode switch in progress; retry"}
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
            self._readiness.clear(target)
            worker.send(cmd, who=who, raw=raw)
        result = {"ok": True, "target": target, "cmd": cmd, "who": who}
        if raw_hex is not None:
            result["raw_hex"] = raw.hex()
        return result

    def exec(self, spec: ExecSpec) -> dict[str, Any]:
        target_name, error = self.resolve_target(spec.target)
        if error is not None:
            if target_name is not None:
                return self._unknown_target_exec(target_name)
            return exec_result("", ok=False, error=error)
        assert target_name is not None
        target = target_name
        with self._state_lock:
            if self._switching:
                return exec_result(
                    target, ok=False, error="mode switch in progress; retry"
                )
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
            self._readiness.clear(target)
            request = worker.enqueue_exec(spec.cmd, **spec.as_exec_options())
        return worker.wait_exec(request)
