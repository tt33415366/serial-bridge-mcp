"""Agent Trace: bounded record of Agent activity and its WebSocket events.

Exec entries are published as ``{"type": "exec", "phase": "start"|"end"}``
messages; Send, Tail, and status reads are published as ``{"type": "trace"}``
messages carrying the whole entry. Every end/read message also carries
``returned_total``, the bytes this Hub session has returned to Agents so far.
"""
from __future__ import annotations

import json
import threading
from collections import deque
from collections.abc import Callable
from typing import Any

from serial_bridge.hub.text import ts


def payload_bytes(result: Any) -> int:
    """UTF-8 size of a tool result as compact JSON: the Agent-facing cost."""
    return len(json.dumps(result, ensure_ascii=False).encode("utf-8"))


class AgentTrace:
    """Record bounded Agent activity and publish lifecycle events."""

    def __init__(self, emit: Callable[[dict[str, Any]], None]) -> None:
        self._emit = emit
        self._lock = threading.Lock()
        self._exec_id = 0
        self._entries: deque[dict[str, Any]] = deque(maxlen=50)
        self._returned_total = 0

    @property
    def returned_total(self) -> int:
        with self._lock:
            return self._returned_total

    def _next_id(self) -> int:
        self._exec_id += 1
        return self._exec_id

    def record_start(self, target: str, cmd: str, prompt: str | None) -> int:
        with self._lock:
            exec_id = self._next_id()
            entry = {
                "id": exec_id,
                "kind": "exec",
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
        returned_bytes: int = 0,
    ) -> None:
        end = {
            "phase": "end",
            "ended_by": ended_by,
            "ms": ms,
            "bytes": bytes,
            "truncated": truncated,
            "ok": ok,
            "returned_bytes": returned_bytes,
        }
        with self._lock:
            self._returned_total += returned_bytes
            total = self._returned_total
            for index, entry in enumerate(self._entries):
                if entry["id"] == id:
                    self._entries[index] = {**entry, **end}
                    break
        self._emit(
            {
                "type": "exec",
                "id": id,
                "target": target,
                **end,
                "returned_total": total,
            }
        )

    def record_read(
        self,
        kind: str,
        *,
        target: str | None,
        ok: bool,
        returned_bytes: int,
        **fields: Any,
    ) -> int:
        """Record one Send, Tail, or status read as a sealed entry."""
        with self._lock:
            entry_id = self._next_id()
            self._returned_total += returned_bytes
            total = self._returned_total
            entry = {
                "id": entry_id,
                "kind": kind,
                "phase": "end",
                "target": target,
                "ts": ts(),
                "ok": ok,
                "returned_bytes": returned_bytes,
                **fields,
            }
            self._entries.append(entry)
        self._emit({"type": "trace", **entry, "returned_total": total})
        return entry_id

    def get_agent_log(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(entry) for entry in reversed(self._entries)]
