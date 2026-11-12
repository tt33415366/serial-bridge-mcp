"""Freshness-bound Shell Readiness: ready only while the newest RX ends at the prompt."""
from __future__ import annotations

import re
import threading

from serial_bridge.hub.text import strip_ansi

_KEEP_CHARS = 512


class ShellReadiness:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tail: dict[str, str] = {}
        self._observed_at: dict[str, str] = {}

    def observe(self, target: str, text: str, at: str) -> None:
        clean = strip_ansi(text)
        with self._lock:
            self._tail[target] = (self._tail.get(target, "") + clean)[-_KEEP_CHARS:]
            self._observed_at[target] = at

    def clear(self, target: str | None = None) -> None:
        with self._lock:
            if target is None:
                self._tail.clear()
                self._observed_at.clear()
            else:
                self._tail.pop(target, None)
                self._observed_at.pop(target, None)

    def evaluate(self, target: str, pattern: str | None) -> tuple[str, str | None]:
        if not pattern:
            return "unknown", None
        with self._lock:
            tail = self._tail.get(target)
            at = self._observed_at.get(target)
        if not tail or at is None:
            return "unknown", None
        last_line = tail.rsplit("\n", 1)[-1].replace("\r", "")
        if not last_line.strip():
            return "unknown", None
        try:
            matched = re.search(pattern, last_line) is not None
        except re.error:
            return "unknown", None
        return ("ready", at) if matched else ("unknown", None)
