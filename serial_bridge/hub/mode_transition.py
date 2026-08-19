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

    def start_bridge(self) -> dict[str, Any]:
        with self._hub._transition_lock:
            with self._hub._state_lock:
                if self._hub.mode == "bridge" and all(
                    key in self._hub.workers and self._hub.workers[key].is_open
                    for key in self._hub.ports
                ):
                    return {
                        "ok": True,
                        "mode": "bridge",
                        "msg": "Already in Bridge Mode",
                    }
            errors: list[str] = []
            self.stop_bridge(quiet=True)
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
            self._transcript.assign_session_logs()
            for key, config in self._hub.ports.items():
                worker = self._worker_factory(key, config["com"], config["baud"])
                try:
                    worker.open()
                    worker.start()
                    with self._hub._state_lock:
                        self._hub.workers[key] = worker
                except SerialException as exc:
                    errors.append(f"{config['com']}: {exc}")
            if errors:
                self.stop_bridge(quiet=True)
                self._hub.emit(
                    {
                        "type": "status",
                        **self._hub.status(),
                        "error": "; ".join(errors),
                    }
                )
                return {
                    "ok": False,
                    "mode": "crt",
                    "error": (
                        "Failed to open serial ports "
                        "(confirm SecureCRT has disconnected the configured ports): "
                        + "; ".join(errors)
                    ),
                }
            with self._hub._state_lock:
                self._hub.mode = "bridge"
            self._hub.emit({"type": "status", **self._hub.status()})
            self._hub.emit(
                {
                    "type": "system",
                    "text": (
                        "Entered Bridge Mode: "
                        "Agent and Operator share both streams below"
                    ),
                }
            )
            self.write_bridge_status()
            return {"ok": True, "mode": "bridge"}

    def stop_bridge(self, quiet: bool = False) -> dict[str, Any]:
        with self._hub._transition_lock:
            with self._hub._state_lock:
                self._hub.mode = "crt"
                workers = list(self._hub.workers.values())
                for worker in workers:
                    worker.abort_agent_work()
                self._hub.workers.clear()
            for worker in workers:
                worker.close()
            if not quiet:
                self._hub.emit({"type": "status", **self._hub.status()})
                ports = "/".join(
                    str(config["com"]) for config in self._hub.ports.values()
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
