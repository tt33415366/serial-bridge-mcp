"""Shared test doubles for HTTP, WebSocket, and MCP adapter tests."""
from __future__ import annotations

import threading
from pathlib import Path

from serial_bridge.constants import TAIL_DEFAULT_N
from serial_bridge.hub.queue import ExecSpec, exec_result
from serial_bridge.hub.transcript import tail_response


class FakeHub:
    def __init__(self):
        self.calls: list[tuple] = []
        self.clients: set[object] = set()
        self.ports = {
            "linux": {
                "name": "linux",
                "title": "Linux",
                "com": "COM8",
                "baud": 57600,
                "log": None,
            },
            "rtos": {
                "name": "rtos",
                "title": "RTOS",
                "com": "COM9",
                "baud": 115200,
                "log": None,
            },
        }

    def resolve_target(self, target):
        if not isinstance(target, str):
            return None, "target must be a Target Name string"
        target_name = target.strip().lower()
        if target_name not in self.ports:
            known = ", ".join(sorted(self.ports))
            return target_name, f"unknown target {target_name!r}; known targets: {known}"
        return target_name, None

    def status(self):
        return {
            "mode": "bridge",
            "ports": {
                name: {
                    "name": cfg["name"],
                    "title": cfg["title"],
                    "com": cfg["com"],
                    "baud": cfg["baud"],
                    "open": True,
                    "busy": name == "rtos",
                }
                for name, cfg in self.ports.items()
            },
        }

    def record_agent_read(self, kind, result, *, target=None, **fields):
        self.calls.append(("trace", kind, target, result.get("ok"), fields))

    def send(self, target, cmd="", who="agent", raw_hex=None):
        target_name, error = self.resolve_target(target)
        if error is not None:
            return {"ok": False, "error": error}
        self.calls.append((target_name, cmd, who, raw_hex))
        result = {
            "ok": True,
            "target": target_name,
            "cmd": cmd,
            "who": who,
        }
        if raw_hex is not None:
            result["raw_hex"] = raw_hex
        return result

    def exec(self, spec: ExecSpec):
        target_name, error = self.resolve_target(spec.target)
        if error is not None:
            if target_name is not None:
                return exec_result(target_name, ok=False, error=error)
            return exec_result("", ok=False, error=error)
        self.calls.append((target_name, spec.cmd, spec.as_exec_options()))
        return {"ok": True, "output": "Linux\n"}

    def start_bridge(self):
        self.calls.append(("mode", "bridge"))
        return {"ok": True, "mode": "bridge"}

    def stop_bridge(self):
        self.calls.append(("mode", "crt"))
        return {"ok": True, "mode": "crt"}

    def get_tail(self, target: str = "both", n: int = 80) -> dict[str, str]:
        out: dict[str, str] = {}
        keys = list(self.ports) if target == "both" else [target]
        for key in keys:
            if key not in self.ports:
                continue
            log_path = self.ports[key].get("log")
            if log_path and Path(log_path).is_file():
                lines = Path(log_path).read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
                out[key] = "\n".join(lines[-n:])
            else:
                out[key] = ""
        return out

    def tail(self, target, n=TAIL_DEFAULT_N, with_timestamps=False):
        result = tail_response(
            target,
            n,
            with_timestamps,
            resolve=self.resolve_target,
            session_log=lambda name: self.ports[name].get("log"),
            read_tail=lambda name, count: self.get_tail(target=name, n=count)[name],
        )
        recorded = ("tail", target, n, result["ok"])
        if result.get("ok"):
            recorded += (with_timestamps,)
        self.calls.append(recorded)
        return result


class BlockingExecHub(FakeHub):
    def __init__(self):
        super().__init__()
        self.exec_started = threading.Event()
        self.release_exec = threading.Event()

    def exec(self, spec: ExecSpec):
        self.exec_started.set()
        self.release_exec.wait(10)
        return super().exec(spec)
