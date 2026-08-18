"""Per-target write queue with operator barge-in and agent FIFO."""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class WriteRequest:
    cmd: str
    who: str
    raw: bytes | None = None
    aborted: threading.Event = field(default_factory=threading.Event)


@dataclass
class ExecRequest(WriteRequest):
    target: str = ""
    prompt: str | None = None
    prompt_is_regex: bool = False
    done: threading.Event = field(default_factory=threading.Event)
    result: dict[str, Any] | None = None

    def finish_queued_abort(self) -> None:
        self.result = exec_result(self.target, ok=False, aborted=True)
        self.done.set()


def exec_result(
    target: str,
    *,
    ok: bool,
    output: str = "",
    truncated: bool = False,
    timed_out: bool = False,
    aborted: bool = False,
    error: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": ok,
        "target": target,
        "output": output,
        "truncated": truncated,
        "timed_out": timed_out,
        "aborted": aborted,
    }
    if error is not None:
        result["error"] = error
    return result


class TargetQueue:
    def __init__(self) -> None:
        self._agent: deque[WriteRequest] = deque()
        self._operator: deque[WriteRequest] = deque()
        self._active_agent: WriteRequest | None = None
        self._lock = threading.Lock()

    def enqueue(self, cmd: str, who: str, raw: bytes | None = None) -> WriteRequest:
        request = WriteRequest(cmd, who, raw)
        with self._lock:
            queue = self._agent if who == "agent" else self._operator
            queue.append(request)
        return request

    def enqueue_exec(
        self,
        target: str,
        cmd: str,
        prompt: str | None = None,
        prompt_is_regex: bool = False,
    ) -> ExecRequest:
        request = ExecRequest(
            cmd=cmd,
            who="agent",
            target=target,
            prompt=prompt,
            prompt_is_regex=prompt_is_regex,
        )
        with self._lock:
            self._agent.append(request)
        return request

    def next_write(self) -> WriteRequest | None:
        with self._lock:
            if self._operator:
                return self._operator.popleft()
            if self._active_agent is not None or not self._agent:
                return None
            self._active_agent = self._agent.popleft()
            return self._active_agent

    def complete(self, request: WriteRequest) -> None:
        with self._lock:
            if self._active_agent is request:
                self._active_agent = None

    def write_if_allowed(self, request: WriteRequest, write: Callable[[], None]) -> bool:
        if request.who != "agent":
            write()
            return True
        with self._lock:
            if self._active_agent is not request or request.aborted.is_set():
                return False
            write()
            return True

    def abort_agents(self) -> None:
        with self._lock:
            if self._active_agent is not None:
                self._active_agent.aborted.set()
                self._active_agent = None
            for request in self._agent:
                request.aborted.set()
                if isinstance(request, ExecRequest):
                    request.finish_queued_abort()
            self._agent.clear()

    @property
    def is_busy(self) -> bool:
        with self._lock:
            return bool(self._active_agent or self._agent or self._operator)
