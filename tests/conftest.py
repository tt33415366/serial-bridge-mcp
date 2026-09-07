"""Shared test doubles for HTTP, WebSocket, and MCP adapter tests."""
from __future__ import annotations

import threading
from pathlib import Path


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

    def send(self, target, cmd="", who="agent", raw_hex=None):
        self.calls.append((target, cmd, who, raw_hex))
        result = {
            "ok": True,
            "target": target,
            "cmd": cmd,
            "who": who,
        }
        if raw_hex is not None:
            result["raw_hex"] = raw_hex
        return result

    def exec(
        self,
        target,
        cmd,
        prompt=None,
        prompt_is_regex=False,
        grep=None,
        grep_is_regex=False,
        grep_context=0,
    ):
        self.calls.append(
            (target, cmd, prompt, prompt_is_regex, grep, grep_is_regex, grep_context)
        )
        return {
            "ok": True,
            "target": target,
            "output": "Linux\n",
            "truncated": False,
            "timed_out": False,
            "aborted": False,
        }

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

    def tail(self, target, n=80):
        from serial_bridge.constants import TAIL_DEFAULT_N, TAIL_MAX_N

        target_name, error = self.resolve_target(target)
        resolved = target_name or ""
        if not isinstance(n, int) or isinstance(n, bool) or n < 1 or n > TAIL_MAX_N:
            echoed = n if isinstance(n, int) and not isinstance(n, bool) else TAIL_DEFAULT_N
            result = {
                "ok": False,
                "target": resolved,
                "tail": "",
                "n": echoed,
                "error": f"n must be an integer from 1 to {TAIL_MAX_N}",
            }
            self.calls.append(("tail", target, n, result["ok"]))
            return result
        if error is not None:
            result = {
                "ok": False,
                "target": resolved,
                "tail": "",
                "n": n,
                "error": error,
            }
            self.calls.append(("tail", target, n, result["ok"]))
            return result
        log_path = self.ports[target_name].get("log")
        if not log_path or not Path(log_path).is_file():
            result = {
                "ok": False,
                "target": target_name,
                "tail": "",
                "n": n,
                "error": "no current Session Log",
            }
            self.calls.append(("tail", target, n, result["ok"]))
            return result
        lines = Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()
        result = {
            "ok": True,
            "target": target_name,
            "tail": "\n".join(lines[-n:]),
            "n": n,
        }
        self.calls.append(("tail", target, n, result["ok"]))
        return result


class BlockingExecHub(FakeHub):
    def __init__(self):
        super().__init__()
        self.exec_started = threading.Event()
        self.release_exec = threading.Event()

    def exec(
        self,
        target,
        cmd,
        prompt=None,
        prompt_is_regex=False,
        grep=None,
        grep_is_regex=False,
        grep_context=0,
    ):
        self.exec_started.set()
        self.release_exec.wait(10)
        return super().exec(
            target,
            cmd,
            prompt,
            prompt_is_regex,
            grep,
            grep_is_regex,
            grep_context,
        )
