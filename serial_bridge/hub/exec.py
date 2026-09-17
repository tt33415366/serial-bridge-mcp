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

    @staticmethod
    def _remove_prompt(
        text: str,
        prompt: str,
        prompt_regex: re.Pattern[str] | None,
    ) -> str:
        """Remove the last prompt match; drop its line if nothing else is on it."""
        if prompt_regex is not None:
            matches = list(prompt_regex.finditer(text))
            if not matches:
                return text
            start, end = matches[-1].span()
        else:
            start = text.rfind(prompt)
            if start < 0:
                return text
            end = start + len(prompt)
        line_start = text.rfind("\n", 0, start) + 1
        newline = text.find("\n", end)
        line_end = len(text) if newline < 0 else newline + 1
        rest = text[line_start:start] + text[end:line_end]
        if not rest.strip():
            rest = ""
        elif start == line_start:
            rest = rest.lstrip(" \t")
        return text[:line_start] + rest + text[line_end:]

    @staticmethod
    def _drop_echo(lines: list[str], cmd: str) -> list[str]:
        """Drop the first non-blank line when the device echoed the command."""
        cmd = cmd.strip()
        if not cmd:
            return lines
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            if line.rstrip().endswith(cmd):
                return lines[index + 1 :]
            break
        return lines

    @classmethod
    def _select_grep_lines(
        cls,
        lines: list[str],
        request: ExecRequest,
        *,
        grep_regex: re.Pattern[str] | None = None,
    ) -> tuple[list[str], int]:
        if grep_regex is not None:
            hit_indices = [
                index for index, line in enumerate(lines) if grep_regex.search(line)
            ]
        else:
            hit_indices = [
                index for index, line in enumerate(lines) if request.grep in line
            ]
        match_count = len(hit_indices)
        if request.grep_invert:
            hits = set(hit_indices)
            selected = [line for index, line in enumerate(lines) if index not in hits]
        elif request.grep_context > 0:
            last = len(lines) - 1
            included: set[int] = set()
            for index in hit_indices:
                start = max(0, index - request.grep_context)
                end = min(last, index + request.grep_context)
                included.update(range(start, end + 1))
            selected = [lines[index] for index in sorted(included)]
        else:
            selected = [lines[index] for index in hit_indices]
        return selected, match_count

    @classmethod
    def _present_output(
        cls,
        text: str,
        request: ExecRequest,
        *,
        grep_regex: re.Pattern[str] | None = None,
        prompt_regex: re.Pattern[str] | None = None,
        prompt_matched: bool = False,
    ) -> tuple[str, bool, dict[str, Any]]:
        extras: dict[str, Any] = {}
        if prompt_matched and request.prompt is not None:
            text = cls._remove_prompt(text, request.prompt, prompt_regex)
        lines = cls._drop_echo(text.splitlines(keepends=True), request.cmd)
        if request.grep is not None:
            lines, match_count = cls._select_grep_lines(
                lines, request, grep_regex=grep_regex
            )
            extras["grepped"] = True
            extras["match_count"] = match_count
        if request.max_lines is not None and len(lines) > request.max_lines:
            extras["lines_dropped"] = len(lines) - request.max_lines
            lines = lines[-request.max_lines :]
        output, truncated = cls._cap_output("".join(lines))
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
        prompt_regex: re.Pattern[str] | None = None,
        prompt_matched: bool = False,
    ) -> dict[str, Any]:
        output, truncated, extras = self._present_output(
            self._strip_output(captured),
            request,
            grep_regex=grep_regex,
            prompt_regex=prompt_regex,
            prompt_matched=prompt_matched,
        )
        return exec_result(
            request.target,
            ok=ok,
            output=output,
            truncated=truncated,
            timed_out=timed_out,
            aborted=aborted,
            error=error,
            **extras,
        )

    @staticmethod
    def _validate(
        request: ExecRequest,
    ) -> tuple[re.Pattern[str] | None, re.Pattern[str] | None, str | None]:
        """Compile regexes and check option combinations before any TX."""
        prompt_regex = grep_regex = None
        if request.prompt is not None and request.prompt_is_regex:
            try:
                prompt_regex = re.compile(request.prompt)
            except re.error as exc:
                return None, None, f"prompt is not a valid regex: {exc}"
        if request.grep is not None and request.grep_is_regex:
            try:
                grep_regex = re.compile(request.grep)
            except re.error as exc:
                return None, None, f"grep is not a valid regex: {exc}"
        if request.grep is not None and request.grep == "":
            return None, None, "grep must not be empty"
        if request.grep_context < 0:
            return None, None, "grep_context must not be negative"
        if request.grep is None:
            if request.grep_context > 0:
                return None, None, "grep_context requires grep"
            if request.grep_invert:
                return None, None, "grep_invert requires grep"
        if request.grep_invert and request.grep_context > 0:
            return None, None, "grep_invert cannot be combined with grep_context"
        if request.max_lines is not None and request.max_lines < 1:
            return None, None, "max_lines must be at least 1"
        if request.prompt_settle_ms < 0:
            return None, None, "prompt_settle_ms must not be negative"
        if request.prompt_settle_ms >= ExecEngine.IDLE_SECONDS * 1000:
            return (
                None,
                None,
                f"prompt_settle_ms must be below {int(ExecEngine.IDLE_SECONDS * 1000)}",
            )
        if request.prompt_settle_ms > 0 and request.prompt is None:
            return None, None, "prompt_settle_ms requires prompt"
        return prompt_regex, grep_regex, None

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
        prompt_regex, grep_regex, error = self._validate(request)
        if error is not None:
            return self._finish(
                on_done,
                "error",
                exec_result(request.target, ok=False, error=error),
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
        settle_seconds = request.prompt_settle_ms / 1000.0
        prompt_matched = False

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

            if chunk and request.prompt is not None and not prompt_matched:
                full_output = self._strip_output(captured)
                prompt_matched = (
                    prompt_regex.search(full_output) is not None
                    if prompt_regex is not None
                    else request.prompt in full_output
                )

            # Settle Window: after the prompt, keep capturing until the device
            # has been quiet for settle_seconds (zero ends on the match itself).
            if prompt_matched and (
                settle_seconds <= 0 or now - last_rx >= settle_seconds
            ):
                return self._finish(
                    on_done,
                    "prompt",
                    self._result_from_capture(
                        request,
                        captured,
                        ok=True,
                        grep_regex=grep_regex,
                        prompt_regex=prompt_regex,
                        prompt_matched=True,
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
                result.get("truncated", False),
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
            result.get("truncated", False),
            result["ok"],
        )
        return result
