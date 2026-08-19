"""Live console transcript persistence and tail reads."""
from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from serial_bridge.hub.text import sanitize_display, strip_ansi, ts


class Transcript:
    """Own session log assignment, append formatting, and tail reads."""

    def __init__(
        self,
        ports: Callable[[], dict[str, dict[str, Any]]],
        live_dir: Callable[[], Path],
        emit: Callable[[dict[str, Any]], None],
        now: Callable[[], datetime],
    ) -> None:
        self._ports = ports
        self._live_dir = live_dir
        self._emit = emit
        self._now = now
        self._lock = threading.Lock()

    def session_log_path(self, name: str, session_time: datetime) -> Path:
        stamp = session_time.strftime("%Y-%m-%d-%H%M%S")
        return self._live_dir() / f"{name}-{stamp}.log"

    def assign_session_logs(self, session_time: datetime | None = None) -> None:
        session_time = session_time or self._now()
        for name, port in self._ports().items():
            path = self.session_log_path(name, session_time)
            port["log"] = path
            path.touch(exist_ok=True)

    def append_log(
        self,
        target: str,
        direction: str,
        text: str,
        who: str = "",
    ) -> None:
        cfg = self._ports()[target]
        log_path = cfg.get("log")
        if log_path is None:
            raise RuntimeError(f"no session log assigned for target {target!r}")
        line = (
            f"{self._now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} "
            f"{direction} [{cfg['title'].upper()}]"
        )
        if who:
            line += f" ({who})"
        line += f" {strip_ansi(text).rstrip()}\n"
        with self._lock:
            with log_path.open("a", encoding="utf-8", errors="replace") as file:
                file.write(line)
        self._emit(
            {
                "type": "line",
                "target": target,
                "direction": direction,
                "who": who,
                "text": sanitize_display(text).rstrip(),
                "ts": ts(),
            }
        )

    def get_tail(self, target: str = "both", n: int = 80) -> dict[str, str]:
        ports = self._ports()
        keys = list(ports) if target == "both" else [target]
        out: dict[str, str] = {}
        for key in keys:
            if key not in ports:
                continue
            log_path = ports[key].get("log")
            if log_path and log_path.is_file():
                lines = log_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                ).splitlines()
                out[key] = "\n".join(lines[-n:])
            else:
                out[key] = ""
        return out
