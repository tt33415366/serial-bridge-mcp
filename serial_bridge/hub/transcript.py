"""Live console transcript persistence and tail reads."""
from __future__ import annotations

import re
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from serial_bridge.constants import TAIL_DEFAULT_N, TAIL_MAX_N
from serial_bridge.hub.text import sanitize_display, strip_ansi, ts

# "2026-09-16 19:56:06.647 <<< [RTOS] (agent) text" as written by append_log.
_LOG_LINE = re.compile(
    r"^\d{4}-\d{2}-\d{2} (?P<time>\d{2}:\d{2}:\d{2}\.\d{3}) "
    r"(?P<direction>\S+) \[[^\]]*\](?P<rest>.*)$"
)


def compact_tail_line(line: str, with_timestamps: bool = False) -> str:
    """Reduce a Session Log line to direction plus text for a Tail.

    The date and Target title are dropped (the caller named the Target); the
    time is kept only on request. Lines not in Session Log format pass through.
    """
    match = _LOG_LINE.match(line)
    if match is None:
        return line
    compact = match.group("direction") + match.group("rest")
    if with_timestamps:
        compact = f"{match.group('time')} {compact}"
    return compact


def tail_response(
    target: object,
    n: int = TAIL_DEFAULT_N,
    with_timestamps: bool = False,
    *,
    resolve: Callable[[object], tuple[str | None, str | None]],
    session_log: Callable[[str], Any],
    read_tail: Callable[[str, int], str],
) -> dict[str, Any]:
    """Build a Tail envelope: validate n, resolve the Target, compact lines."""
    target_name, error = resolve(target)
    resolved = target_name or ""
    if not isinstance(n, int) or isinstance(n, bool) or n < 1 or n > TAIL_MAX_N:
        echoed = n if isinstance(n, int) and not isinstance(n, bool) else TAIL_DEFAULT_N
        return {
            "ok": False,
            "target": resolved,
            "tail": "",
            "n": echoed,
            "error": f"n must be an integer from 1 to {TAIL_MAX_N}",
        }
    if error is not None:
        return {
            "ok": False,
            "target": resolved,
            "tail": "",
            "n": n,
            "error": error,
        }
    assert target_name is not None
    path = session_log(target_name)
    if not path or not Path(path).is_file():
        return {
            "ok": False,
            "target": target_name,
            "tail": "",
            "n": n,
            "error": "no current Session Log",
        }
    raw = read_tail(target_name, n)
    return {
        "ok": True,
        "target": target_name,
        "tail": "\n".join(
            compact_tail_line(line, with_timestamps) for line in raw.split("\n")
        ),
        "n": n,
    }


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
