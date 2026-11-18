"""Bridge/CRT mode transitions and serial worker lifecycle."""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from serial import SerialException

from serial_bridge.hub.transcript import Transcript


class ModeTransition:
    """Own Bridge/CRT transitions behind Hub's mode facade."""

    def __init__(
        self,
        hub: Any,
        transcript: Transcript,
        worker_factory: Callable[[str, str, int], Any],
    ) -> None:
        self._hub = hub
        self._transcript = transcript
        self._worker_factory = worker_factory

    def write_bridge_status(self) -> None:
        live_dir = self._hub.config.live_dir
        if not live_dir.is_dir():
            return
        (live_dir / "bridge_status.json").write_text(
            json.dumps(self._hub.status(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def start_bridge(self, dut: str | None = None) -> dict[str, Any]:
        keys = self._hub.port_keys(dut)
        with self._hub._transition_lock:
            with self._hub._state_lock:
                owners = {self._hub._port_dut.get(key) for key in keys}
                selected_bridge = bool(keys) and all(
                    self._hub._dut_mode.get(owner) == "bridge" for owner in owners
                )
                if selected_bridge and all(
                    key in self._hub.workers and self._hub.workers[key].is_open
                    for key in keys
                ):
                    return {
                        "ok": True,
                        "mode": "bridge",
                        "msg": "Already in Bridge Mode",
                        "all_open": True,
                        "ports": {key: {"open": True} for key in keys},
                    }
                already_bridge = selected_bridge
            if already_bridge:
                return self._retry_bridge(keys)
            for key in keys:
                self._hub.clear_readiness(key)
            self.stop_bridge(quiet=True, dut=dut)
            try:
                self._hub.config.live_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                self._hub.emit(
                    {
                        "type": "status",
                        **self._hub.status(),
                        "error": f"Could not create Live Directory: {exc}",
                    }
                )
                return {
                    "ok": False,
                    "mode": "crt",
                    "error": f"Could not create Live Directory: {exc}",
                }
            self._transcript.assign_session_logs(keys=keys)
            results: dict[str, dict[str, Any]] = {}
            for key in keys:
                results[key] = self._open_target(key, self._hub.ports[key])
            with self._hub._state_lock:
                for owner in {self._hub._port_dut.get(key) for key in keys}:
                    if owner is not None:
                        self._hub.set_dut_mode(owner, "bridge")
            self._hub.emit({"type": "status", **self._hub.status()})
            streams = "both streams" if len(keys) > 1 else "the stream"
            self._hub.emit(
                {
                    "type": "system",
                    "text": (
                        "Entered Bridge Mode: "
                        f"Agent and Operator share {streams} below"
                    ),
                }
            )
            failed = [key for key, result in results.items() if not result["open"]]
            if failed:
                self._hub.emit(
                    {
                        "type": "system",
                        "text": "Bridge Mode: not open - "
                        + "; ".join(f"{key}: {results[key]['error']}" for key in failed),
                    }
                )
            self.write_bridge_status()
            return {
                "ok": True,
                "mode": "bridge",
                "all_open": not failed,
                "ports": results,
            }

    def _open_target(self, key: str, config: dict[str, Any]) -> dict[str, Any]:
        worker = self._worker_factory(key, config["com"], config["baud"])
        try:
            worker.open()
            worker.start()
            with self._hub._state_lock:
                self._hub.workers[key] = worker
            return {"open": True}
        except SerialException as exc:
            message = f"{config['com']}: {exc}"
            worker.close()
            with self._hub._state_lock:
                self._hub.open_errors[key] = message
            return {"open": False, "error": message}

    def _retry_bridge(self, keys: list[str]) -> dict[str, Any]:
        """Repeat Bridge request: reopen only Targets that are not open.

        Open Targets keep their worker, Session Log, readiness and queued work.
        Session Logs were assigned on entry; a retried Target appends to its log.
        Caller holds the transition lock.
        """
        with self._hub._state_lock:
            retry = [
                key
                for key in keys
                if key not in self._hub.workers or not self._hub.workers[key].is_open
            ]
            dead = [
                self._hub.workers.pop(key)
                for key in retry
                if key in self._hub.workers
            ]
            for key in retry:
                self._hub.open_errors.pop(key, None)
        for worker in dead:
            worker.close()
        results: dict[str, dict[str, Any]] = {key: {"open": True} for key in keys}
        for key in retry:
            self._hub.clear_readiness(key)
            results[key] = self._open_target(key, self._hub.ports[key])
        self._hub.emit({"type": "status", **self._hub.status()})
        failed = [key for key in retry if not results[key]["open"]]
        if failed:
            self._hub.emit(
                {
                    "type": "system",
                    "text": "Bridge Mode: not open - "
                    + "; ".join(f"{key}: {results[key]['error']}" for key in failed),
                }
            )
        self.write_bridge_status()
        return {
            "ok": True,
            "mode": "bridge",
            "all_open": not failed,
            "ports": results,
        }

    def stop_bridge(self, quiet: bool = False, dut: str | None = None) -> dict[str, Any]:
        keys = self._hub.port_keys(dut)
        with self._hub._transition_lock:
            with self._hub._state_lock:
                for owner in {self._hub._port_dut.get(key) for key in keys}:
                    if owner is not None:
                        self._hub.set_dut_mode(owner, "crt")
                for key in keys:
                    self._hub.open_errors.pop(key, None)
                workers = [
                    self._hub.workers.pop(key)
                    for key in keys
                    if key in self._hub.workers
                ]
                for worker in workers:
                    worker.abort_agent_work()
            for worker in workers:
                worker.close()
            for key in keys:
                self._hub.clear_readiness(key)
            if not quiet:
                self._hub.emit({"type": "status", **self._hub.status()})
                ports = "/".join(
                    str(self._hub.ports[key]["com"]) for key in keys if key in self._hub.ports
                )
                self._hub.emit(
                    {
                        "type": "system",
                        "text": (
                            "Switched to CRT Mode: ports released; "
                            f"SecureCRT can connect to {ports}"
                        ),
                    }
                )
            self.write_bridge_status()
            return {"ok": True, "mode": "crt"}
