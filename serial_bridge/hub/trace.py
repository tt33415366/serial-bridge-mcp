"""Agent Exec supervision trace and WebSocket event contract."""
from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from typing import Any

from serial_bridge.hub.text import ts


class AgentTrace:
    """Record bounded Exec history and publish lifecycle events."""

    def __init__(self, emit: Callable[[dict[str, Any]], None]) -> None:
        self._emit = emit
        self._lock = threading.Lock()
        self._exec_id = 0
        self._entries: deque[dict[str, Any]] = deque(maxlen=50)

    def record_start(self, target: str, cmd: str, prompt: str | None) -> int:
        with self._lock:
            self._exec_id += 1
            exec_id = self._exec_id
            entry = {
                "id": exec_id,
                "phase": "start",
                "target": target,
                "cmd": cmd,
                "prompt": prompt,
                "ts": ts(),
            }
            self._entries.append(entry)
        self._emit({"type": "exec", **entry})
        return exec_id

    def record_end(
        self,
        id: int,
        target: str,
        ended_by: str,
        ms: int,
        bytes: int,
        truncated: bool,
        ok: bool,
    ) -> None:
        end = {
            "phase": "end",
            "ended_by": ended_by,
            "ms": ms,
            "bytes": bytes,
            "truncated": truncated,
            "ok": ok,
        }
        with self._lock:
            for index, entry in enumerate(self._entries):
                if entry["id"] == id:
                    self._entries[index] = {**entry, **end}
                    break
        self._emit(
            {
                "type": "exec",
                "phase": "end",
                "id": id,
                "target": target,
                "ended_by": ended_by,
                "ms": ms,
                "bytes": bytes,
                "truncated": truncated,
                "ok": ok,
            }
        )

    def get_agent_log(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(entry) for entry in reversed(self._entries)]
