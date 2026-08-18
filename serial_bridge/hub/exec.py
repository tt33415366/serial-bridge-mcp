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
    def _clean_output(cls, captured: bytearray) -> tuple[str, bool]:
        return cls._cap_output(cls._strip_output(captured))

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
        prompt_regex = None
        if request.prompt is not None and request.prompt_is_regex:
            try:
                prompt_regex = re.compile(request.prompt)
            except re.error as exc:
                return exec_result(
                    request.target,
                    ok=False,
                    error=f"prompt is not a valid regex: {exc}",
                )

        raw_command = request.cmd.encode("utf-8", errors="replace") + line_ending
        wrote = queue.write_if_allowed(request, lambda: serial_port.write(raw_command))
        if not wrote:
            return exec_result(request.target, ok=False, aborted=True)
        serial_port.flush()
        if on_tx is not None:
            on_tx()

        started = self._clock()
        last_rx = started
        captured = bytearray()

        while True:
            if request.aborted.is_set():
                output, truncated = self._clean_output(captured)
                return exec_result(
                    request.target,
                    ok=False,
                    output=output,
                    truncated=truncated,
                    aborted=True,
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
                output, truncated = self._clean_output(captured)
                return exec_result(
                    request.target,
                    ok=False,
                    output=output,
                    truncated=truncated,
                    timed_out=True,
                )

            if chunk:
                full_output = self._strip_output(captured)
                output, truncated = self._cap_output(full_output)
                if request.prompt is not None:
                    matched = (
                        prompt_regex.search(full_output) is not None
                        if prompt_regex is not None
                        else request.prompt in full_output
                    )
                    if matched:
                        return exec_result(
                            request.target,
                            ok=True,
                            output=output,
                            truncated=truncated,
                        )

            if now - last_rx >= self.IDLE_SECONDS:
                output, truncated = self._clean_output(captured)
                return exec_result(
                    request.target,
                    ok=True,
                    output=output,
                    truncated=truncated,
                )
            if not chunk:
                self._sleep(self.POLL_SECONDS)
