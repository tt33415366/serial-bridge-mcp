"""Blocking Exec engine: prompt match, idle completion, and output caps."""
from __future__ import annotations

import re
import time
from typing import Any, Callable

from serial_bridge.hub.queue import ExecRequest, TargetQueue, exec_result
from serial_bridge.hub.text import strip_ansi


class ExecEngine:
    IDLE_SECONDS = 1.0
    TOTAL_SECONDS = 60.0
    OUTPUT_CAP_BYTES = 32 * 1024
    POLL_SECONDS = 0.05

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._clock = clock
        self._sleep = sleep

    @property
    def clock(self) -> Callable[[], float]:
        return self._clock

    @classmethod
    def _strip_output(cls, captured: bytearray) -> str:
        return strip_ansi(captured.decode("utf-8", errors="replace"))

    @classmethod
    def _cap_output(cls, text: str) -> tuple[str, bool]:
        encoded = text.encode("utf-8")
        if len(encoded) <= cls.OUTPUT_CAP_BYTES:
            return text, False
        trailing = encoded[-cls.OUTPUT_CAP_BYTES :]
        while trailing and trailing[0] & 0xC0 == 0x80:
            trailing = trailing[1:]
        return trailing.decode("utf-8", errors="replace"), True

    @classmethod
    def _present_output(
        cls,
        text: str,
        request: ExecRequest,
        *,
        grep_regex: re.Pattern[str] | None = None,
    ) -> tuple[str, bool, dict[str, Any]]:
        extras: dict[str, Any] = {}
        if request.grep is not None:
            lines = text.splitlines(keepends=True)
            if grep_regex is not None:
                matching = [line for line in lines if grep_regex.search(line)]
            else:
                matching = [line for line in lines if request.grep in line]
            text = "".join(matching)
            extras["grepped"] = True
            extras["match_count"] = len(matching)
        output, truncated = cls._cap_output(text)
        return output, truncated, extras

    def _result_from_capture(
        self,
        request: ExecRequest,
        captured: bytearray,
        *,
        ok: bool,
        timed_out: bool = False,
        aborted: bool = False,
        error: str | None = None,
        grep_regex: re.Pattern[str] | None = None,
    ) -> dict[str, Any]:
        output, truncated, extras = self._present_output(
            self._strip_output(captured), request, grep_regex=grep_regex
        )
        return exec_result(
            request.target,
            ok=ok,
            output=output,
            truncated=truncated,
            timed_out=timed_out,
            aborted=aborted,
            error=error,
            grepped=extras.get("grepped"),
            match_count=extras.get("match_count"),
        )

    @staticmethod
    def _finish(
        on_done: Callable[[str], None] | None,
        ended_by: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        if on_done is not None:
            on_done(ended_by)
        return result

    def execute(
        self,
        serial_port: Any,
        queue: TargetQueue,
        request: ExecRequest,
        line_ending: bytes,
        *,
        on_tx: Callable[[], None] | None = None,
        on_rx: Callable[[bytes], None] | None = None,
        service_operator: Callable[[], None] | None = None,
        on_done: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        captured = bytearray()
        prompt_regex = None
        if request.prompt is not None and request.prompt_is_regex:
            try:
                prompt_regex = re.compile(request.prompt)
            except re.error as exc:
                return self._finish(
                    on_done,
                    "error",
                    exec_result(
                        request.target,
                        ok=False,
                        error=f"prompt is not a valid regex: {exc}",
                    ),
                )

        grep_regex = None
        if request.grep is not None and request.grep_is_regex:
            try:
                grep_regex = re.compile(request.grep)
            except re.error as exc:
                return self._finish(
                    on_done,
                    "error",
                    exec_result(
                        request.target,
                        ok=False,
                        error=f"grep is not a valid regex: {exc}",
                    ),
                )

        if request.grep is not None and request.grep == "":
            return self._finish(
                on_done,
                "error",
                exec_result(
                    request.target,
                    ok=False,
                    error="grep must not be empty",
                ),
            )

        raw_command = request.cmd.encode("utf-8", errors="replace") + line_ending
        wrote = queue.write_if_allowed(request, lambda: serial_port.write(raw_command))
        if not wrote:
            return self._finish(
                on_done,
                "abort",
                exec_result(request.target, ok=False, aborted=True),
            )
        serial_port.flush()
        if on_tx is not None:
            on_tx()

        started = self._clock()
        last_rx = started

        while True:
            if request.aborted.is_set():
                return self._finish(
                    on_done,
                    "abort",
                    self._result_from_capture(
                        request,
                        captured,
                        ok=False,
                        aborted=True,
                        grep_regex=grep_regex,
                    ),
                )

            if service_operator is not None:
                service_operator()

            chunk = serial_port.read(4096)
            if chunk:
                captured.extend(chunk)
                last_rx = self._clock()
                if on_rx is not None:
                    on_rx(chunk)

            now = self._clock()
            if now - started >= self.TOTAL_SECONDS:
                return self._finish(
                    on_done,
                    "timeout",
                    self._result_from_capture(
                        request,
                        captured,
                        ok=False,
                        timed_out=True,
                        grep_regex=grep_regex,
                    ),
                )

            if chunk:
                full_output = self._strip_output(captured)
                if request.prompt is not None:
                    matched = (
                        prompt_regex.search(full_output) is not None
                        if prompt_regex is not None
                        else request.prompt in full_output
                    )
                    if matched:
                        return self._finish(
                            on_done,
                            "prompt",
                            self._result_from_capture(
                                request,
                                captured,
                                ok=True,
                                grep_regex=grep_regex,
                            ),
                        )

            if now - last_rx >= self.IDLE_SECONDS:
                return self._finish(
                    on_done,
                    "idle",
                    self._result_from_capture(
                        request,
                        captured,
                        ok=True,
                        grep_regex=grep_regex,
                    ),
                )
            if not chunk:
                self._sleep(self.POLL_SECONDS)


class ExecSession:
    """Own one Exec result and its supervision lifecycle."""

    def __init__(
        self,
        hub: Any,
        engine: ExecEngine,
    ) -> None:
        self._hub = hub
        self._engine = engine
        self._clock = engine.clock

    def execute(
        self,
        serial_port: Any,
        queue: TargetQueue,
        request: ExecRequest,
        line_ending: bytes,
        *,
        on_tx: Callable[[], None] | None = None,
        on_rx: Callable[[bytes], None] | None = None,
        service_operator: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        exec_id = self._hub.record_exec_start(
            request.target,
            request.cmd,
            request.prompt,
        )
        started = self._clock()
        captured_bytes_seen = 0
        ended_by: str | None = None

        def handle_rx(chunk: bytes) -> None:
            nonlocal captured_bytes_seen
            captured_bytes_seen += len(chunk)
            if on_rx is not None:
                on_rx(chunk)

        def handle_done(completion: str) -> None:
            nonlocal ended_by
            ended_by = completion

        try:
            result = self._engine.execute(
                serial_port,
                queue,
                request,
                line_ending,
                on_tx=on_tx,
                on_rx=handle_rx,
                service_operator=service_operator,
                on_done=handle_done,
            )
        except Exception:
            ended_by = "error"
            result = exec_result(
                request.target,
                ok=False,
                error="Exec failed",
            )
            self._hub.record_exec_end(
                exec_id,
                request.target,
                ended_by,
                int((self._clock() - started) * 1000),
                captured_bytes_seen,
                result["truncated"],
                result["ok"],
            )
            raise

        if ended_by is None:
            ended_by = "error"
            result = exec_result(
                request.target,
                ok=False,
                error="Exec failed",
            )

        self._hub.record_exec_end(
            exec_id,
            request.target,
            ended_by,
            int((self._clock() - started) * 1000),
            captured_bytes_seen,
            result["truncated"],
            result["ok"],
        )
        return result
