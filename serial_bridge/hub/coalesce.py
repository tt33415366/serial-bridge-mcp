"""Batch live console line events so flood RX does not saturate WebSocket."""
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any


class LineCoalescer:
    """Own line buffering; callers emit any Hub event through this seam."""

    FLUSH_SECONDS = 0.05

    def __init__(
        self,
        dispatch: Callable[[dict[str, Any]], None],
        *,
        timer_factory: Callable[[float, Callable[[], None]], Any] = threading.Timer,
    ) -> None:
        self._dispatch = dispatch
        self._timer_factory = timer_factory
        self._lock = threading.Lock()
        self._pending: list[dict[str, Any]] = []
        self._timer: threading.Timer | None = None

    def emit(self, msg: dict[str, Any]) -> None:
        if msg.get("type") == "line":
            self._buffer_line(msg)
            return
        self.flush()
        self._dispatch(msg)

    def _buffer_line(self, msg: dict[str, Any]) -> None:
        with self._lock:
            self._pending.append(msg)
            if self._timer is not None:
                return
            timer = self._timer_factory(self.FLUSH_SECONDS, self.flush)
            timer.daemon = True
            self._timer = timer
            timer.start()

    def flush(self) -> None:
        with self._lock:
            lines = self._pending
            self._pending = []
            timer, self._timer = self._timer, None
        if timer is not None:
            timer.cancel()
        if not lines:
            return
        if len(lines) == 1:
            self._dispatch(lines[0])
            return
        items = [{key: value for key, value in line.items() if key != "type"} for line in lines]
        self._dispatch({"type": "line", "items": items})
