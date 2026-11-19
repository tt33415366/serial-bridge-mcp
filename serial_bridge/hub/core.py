"""Serial ownership, mode, transcript, and WebSocket broadcast authority."""
from __future__ import annotations

import asyncio
import json
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlencode

from serial_bridge.config import (
    MAX_SLOT_COUNT,
    Config,
    SlotPolicy,
    _assert_unique_target_names,
    _validated_name,
    _validated_slots,
    _validated_title,
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
        self._dut_mode: dict[str, str] = {}
        self._port_dut: dict[str, str] = {}
        seen_targets: set[str] = set()
        for dut in self.config.duts:
            dut_name = str(dut["name"])
            self._dut_mode[dut_name] = "crt"
            for slot in dut["slots"]:  # type: ignore[union-attr]
                self._register_slot(dut_name, slot, seen_targets)
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

    @property
    def mode(self) -> str:
        values = set(self._dut_mode.values())
        if len(values) == 1:
            return next(iter(values))
        return "mixed"

    @mode.setter
    def mode(self, value: str) -> None:
        for name in self._dut_mode:
            self._dut_mode[name] = value

    def port_keys(self, dut: str | None = None) -> list[str]:
        if dut is None:
            return list(self.ports)
        return [key for key in self.ports if self._owner(key) == dut]

    def _owner(self, key: str) -> str:
        return self._port_dut.get(key) or self._first_dut_name()

    def set_dut_mode(self, dut: str | None, value: str) -> None:
        if dut is None:
            self.mode = value
            return
        self._dut_mode[dut] = value

    def _register_slot(
        self,
        dut: str,
        slot: Mapping[str, str | int],
        seen_targets: set[str],
    ) -> str:
        target = str(slot["name"])
        key = target if target not in seen_targets else f"{dut}/{target}"
        seen_targets.add(target)
        self._port_dut[key] = dut
        self.ports[key] = {
            "name": target,
            "title": str(slot["title"]),
            "com": str(slot["com"]),
            "baud": int(slot["baud"]),
            "log": None,
            "dut": dut,
        }
        return key

    def _session_log_path(self, name: str, session_time) -> Path:
        return self._transcript.session_log_path(name, session_time)

    def _assign_session_logs(self, session_time=None) -> None:
        self._transcript.assign_session_logs(session_time)

    def _write_bridge_status(self) -> None:
        self._mode_transition.write_bridge_status()

    def _apply_slot_updates(
        self, slots: list[dict[str, str | int]], dut: str | None = None
    ) -> None:
        dut_name = dut or self._first_dut_name()
        old_by_name: dict[str, dict[str, Any]] = {}
        for key in self.port_keys(dut_name):
            entry = self.ports.pop(key)
            old_by_name[str(entry["name"])] = entry
            self._port_dut.pop(key, None)
        seen = {str(port["name"]) for port in self.ports.values()}
        for slot in slots:
            key = self._register_slot(dut_name, slot, seen)
            prior = old_by_name.get(str(slot["name"]))
            if prior is not None:
                fresh = {k: v for k, v in self.ports[key].items() if k != "log"}
                self.ports[key] = {**prior, **fresh}
        order = {str(d["name"]): i for i, d in enumerate(self.config.duts)}
        self.ports = dict(
            sorted(self.ports.items(), key=lambda kv: order[self._owner(kv[0])])
        )
        index = order[dut_name]
        self.config.duts[index]["slots"] = slots
        if index == 0:
            self.config.slots = slots
        self.config.warning = None
    def resolve_target(
        self, dut: object, target: object
    ) -> tuple[str | None, str | None]:
        """Map (DUT Name, Target Name) to the internal port key, or an error."""
        if not isinstance(dut, str):
            return None, "dut must be a DUT Name string"
        dut_name = dut.strip().lower()
        if self._dut_index(dut_name) is None:
            known = ", ".join(str(d["name"]) for d in self.config.duts)
            return None, f"unknown DUT {dut_name!r}; known DUTs: {known}"
        if not isinstance(target, str):
            return None, "target must be a Target Name string"
        target_name = target.strip().lower()
        keys = self.port_keys(dut_name)
        for key in keys:
            if self.ports[key]["name"] == target_name:
                return key, None
        known = ", ".join(sorted(str(self.ports[k]["name"]) for k in keys))
        return target_name, (
            f"unknown target {target_name!r} in DUT {dut_name!r}; "
            f"known targets: {known}"
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
            dut_modes = dict(self._dut_mode)
            port_dut = dict(self._port_dut)
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
                        f"{SESSION_LOG_ROUTE}?"
                        + urlencode({"dut": v["dut"], "target": v["name"]})
                        if v.get("log")
                        else ""
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
        status["duts"] = [
            {
                "name": str(dut["name"]),
                "title": str(dut["title"]),
                "mode": dut_modes.get(str(dut["name"]), "crt"),
                "ports": {
                    key: status["ports"][key]
                    for key, owner in port_dut.items()
                    if owner == dut["name"] and key in status["ports"]
                },
            }
            for dut in self.config.duts
        ]
        return status

    def agent_status(self) -> dict[str, Any]:
        """Agent-facing status: every DUT grouped, Targets keyed by Target Name."""
        status = self.status()
        allowed = status["mode_switch"]["allowed"]
        duts = []
        for dut in status["duts"]:
            ports = {p["name"]: p for p in dut["ports"].values()}
            busy_targets = sorted(n for n, p in ports.items() if p["busy"])
            duts.append(
                {
                    "name": dut["name"],
                    "title": dut["title"],
                    "mode": dut["mode"],
                    "mode_switch": self._mode_switch_for(busy_targets, allowed),
                    "ports": ports,
                }
            )
        result: dict[str, Any] = {"duts": duts}
        if "config_warning" in status:
            result["config_warning"] = status["config_warning"]
        return result

    @staticmethod
    def _mode_switch_info(workers: dict[str, Any], allowed: bool) -> dict[str, Any]:
        busy_targets = sorted(k for k, w in workers.items() if w.is_busy)
        return Hub._mode_switch_for(busy_targets, allowed)

    @staticmethod
    def _mode_switch_for(busy_targets: list[str], allowed: bool) -> dict[str, Any]:
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
        dut: str,
        target: str,
        n: int = TAIL_DEFAULT_N,
        with_timestamps: bool = False,
    ) -> dict[str, Any]:
        result = tail_response(
            target,
            n,
            with_timestamps,
            resolve=lambda value: self.resolve_target(dut, value),
            session_log=lambda name: self.ports[name].get("log"),
            read_tail=lambda name, count: self.get_tail(target=name, n=count)[name],
        )
        key, error = self.resolve_target(dut, target)
        return result if error is not None else self._echo_target(result, key)

    def _echo_target(self, result: dict[str, Any], key: str | None) -> dict[str, Any]:
        """Report the caller's (DUT, Target Name) instead of the internal port key."""
        assert key is not None
        result["target"] = self.ports[key]["name"]
        result["dut"] = self._owner(key)
        return result

    def update_slots(
        self,
        slots: list[dict[str, str | int | object]],
        live_dir: str | None = None,
        dut: str | None = None,
    ) -> dict[str, Any]:
        with self._transition_lock:
            with self._state_lock:
                dut_name = dut or self._first_dut_name()
                index = self._dut_index(dut_name)
                if index is None:
                    return {"ok": False, "error": f"unknown DUT {dut_name!r}"}
                current = self.config.duts[index]["slots"]
                policy_args: dict[str, Any] = {}
                if index != 0:
                    policy_args["current"] = current
                decision = self._slot_policy.decide(
                    slots,
                    live_dir=live_dir,
                    mode=self._dut_mode[dut_name],
                    has_workers=any(k in self.workers for k in self.port_keys(dut_name)),
                    **policy_args,
                )
                if not decision.allowed:
                    return {"ok": False, "error": decision.error}

                taken = {
                    str(slot["com"])
                    for i, d in enumerate(self.config.duts)
                    if i != index
                    for slot in d["slots"]  # type: ignore[union-attr]
                }
                if any(str(slot.get("com")) in taken for slot in slots):
                    return {
                        "ok": False,
                        "error": "A COM port belongs to at most one Target",
                    }

                old_live_dir = self.config.live_dir
                try:
                    if decision.live_dir is not None:
                        self.config.live_dir = decision.live_dir
                    validated = persist_slots(self.config, slots, index)
                except (OSError, UnicodeError, ValueError) as exc:
                    self.config.live_dir = old_live_dir
                    return {"ok": False, "error": f"Could not save Port Bindings: {exc}"}

                self._apply_slot_updates(validated, dut_name)

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

    def set_target_prompt(
        self, dut: object, target: object, pattern: object
    ) -> dict[str, Any]:
        """Operator-only: set or clear (empty string) a Target's Target Prompt."""
        target_name, error = self.resolve_target(dut, target)
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

    def start_bridge(self, dut: str | None = None) -> dict[str, Any]:
        if dut is not None and dut not in self._dut_mode:
            return {
                "ok": False,
                "error": f"unknown DUT {dut!r}",
                "mode": self.mode,
            }
        if dut is None:
            return self._mode_transition.start_bridge()
        return self._mode_transition.start_bridge(dut)

    def stop_bridge(self, quiet: bool = False, dut: str | None = None) -> dict[str, Any]:
        if dut is not None and dut not in self._dut_mode:
            return {
                "ok": False,
                "error": f"unknown DUT {dut!r}",
                "mode": self.mode,
            }
        if dut is None:
            return self._mode_transition.stop_bridge(quiet)
        return self._mode_transition.stop_bridge(quiet, dut)

    def _first_dut_name(self) -> str:
        return str(self.config.duts[0]["name"])

    def _dut_index(self, name: str) -> int | None:
        return next(
            (i for i, d in enumerate(self.config.duts) if str(d["name"]) == name),
            None,
        )

    def _persist_duts(self) -> None:
        persist_slots(self.config, list(self.config.duts[0]["slots"]))  # type: ignore[arg-type]

    def _drop_dut_ports(self, dut: str) -> None:
        for key in self.port_keys(dut):
            self.ports.pop(key, None)
            self._port_dut.pop(key, None)

    def _publish_status(self) -> dict[str, Any]:
        status = self.status()
        self.emit({"type": "status", **status})
        return {"ok": True, **status}

    def add_dut(
        self,
        name: str,
        title: str,
        slots: list[dict[str, str | int]],
    ) -> dict[str, Any]:
        try:
            dut_name = _validated_name(name, "name")
            dut_title = _validated_title(title, "title")
            validated = _validated_slots({"slots": list(slots)})
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if self._dut_index(dut_name) is not None:
            return {"ok": False, "error": "DUT Names must be unique"}
        taken = {
            str(slot["com"])
            for dut in self.config.duts
            for slot in dut["slots"]  # type: ignore[union-attr]
        }
        for slot in validated:
            if str(slot["com"]) in taken:
                return {"ok": False, "error": "A COM port belongs to at most one Target"}
            taken.add(str(slot["com"]))
        try:
            _assert_unique_target_names(validated)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        self.config.duts.append(
            {"name": dut_name, "title": dut_title, "slots": validated}
        )
        self._dut_mode[dut_name] = "crt"
        seen = {str(port["name"]) for port in self.ports.values()}
        try:
            for slot in validated:
                self._register_slot(dut_name, slot, seen)
            self._persist_duts()
        except (OSError, UnicodeError, ValueError) as exc:
            self.config.duts.pop()
            self._drop_dut_ports(dut_name)
            self._dut_mode.pop(dut_name, None)
            return {"ok": False, "error": f"Could not save DUT: {exc}"}
        return self._publish_status()

    def remove_dut(self, name: str) -> dict[str, Any]:
        with self._transition_lock:
            index = self._dut_index(name)
            if index is None:
                return {"ok": False, "error": f"unknown DUT {name!r}"}
            if len(self.config.duts) == 1:
                return {"ok": False, "error": "The last DUT cannot be removed"}
            if self._dut_mode[name] != "crt":
                stopped = self.stop_bridge(True, name)
                if not stopped.get("ok", True):
                    return {"ok": False, "error": stopped.get("error", "could not stop DUT")}
            with self._state_lock:
                keys = self.port_keys(name)
                if self._dut_mode[name] != "crt" or any(k in self.workers for k in keys):
                    return {"ok": False, "error": "DUT is still holding its ports"}
                removed = self.config.duts.pop(index)
                old_slots = self.config.slots
                try:
                    self._persist_duts()
                except (OSError, UnicodeError, ValueError) as exc:
                    self.config.duts.insert(index, removed)
                    self.config.slots = old_slots
                    return {"ok": False, "error": f"Could not save DUT: {exc}"}
                self._drop_dut_ports(name)
                self._dut_mode.pop(name, None)
        return self._publish_status()

    def rename_dut(self, name: str, title: str) -> dict[str, Any]:
        try:
            new_title = _validated_title(title, "title")
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        index = self._dut_index(name)
        if index is None:
            return {"ok": False, "error": f"Unknown DUT: {name}"}
        dut = self.config.duts[index]
        old_title = dut["title"]
        dut["title"] = new_title
        try:
            self._persist_duts()
        except (OSError, UnicodeError, ValueError) as exc:
            dut["title"] = old_title
            return {"ok": False, "error": f"Could not save DUT: {exc}"}
        return self._publish_status()

    def _dut_is_bridge(self, target: str) -> bool:
        dut = self._port_dut.get(target)
        if dut is None:
            return self.mode == "bridge"
        return self._dut_mode.get(dut) == "bridge"

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
        dut: object,
        target: object,
        cmd: str = "",
        who: str = "user",
        raw_hex: str | None = None,
    ) -> dict[str, Any]:
        result = self._send(dut, target, cmd, who, raw_hex)
        key = result.get("target")
        if who == "agent":
            self._agent_trace.record_read(
                "send",
                target=result.get("target") or (target if isinstance(target, str) else None),
                ok=bool(result["ok"]),
                returned_bytes=payload_bytes(result),
                cmd=cmd if raw_hex is None else f"[raw] {raw_hex}",
            )
        return self._echo_target(result, key) if key in self.ports else result

    def _send(
        self,
        dut: object,
        target: object,
        cmd: str,
        who: str,
        raw_hex: str | None,
    ) -> dict[str, Any]:
        target_name, error = self.resolve_target(dut, target)
        if error is not None:
            return {"ok": False, "error": error}
        assert target_name is not None
        target = target_name
        with self._state_lock:
            if self._switching:
                return {"ok": False, "error": "mode switch in progress; retry"}
            if not self._dut_is_bridge(target):
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
        key, error = self.resolve_target(spec.dut, spec.target)
        if error is not None:
            return exec_result(key or "", ok=False, error=error)
        return self._echo_target(self._exec(key, spec), key)

    def _exec(self, target_name: str | None, spec: ExecSpec) -> dict[str, Any]:
        assert target_name is not None
        target = target_name
        with self._state_lock:
            if self._switching:
                return exec_result(
                    target, ok=False, error="mode switch in progress; retry"
                )
            if not self._dut_is_bridge(target):
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
