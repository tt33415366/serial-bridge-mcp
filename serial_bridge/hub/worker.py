"""Per-target serial thread: TX queue, RX logging, and Exec delegation."""
from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any

import serial
from serial import SerialException

from serial_bridge.hub.exec import ExecEngine, ExecSession
from serial_bridge.hub.queue import ExecRequest, TargetQueue, WriteRequest, exec_result

if TYPE_CHECKING:
    from serial_bridge.hub.core import Hub


class PortWorker:
    def __init__(self, name: str, port: str, baud: int, hub_ref: Hub):
        self.name = name
        self.port = port
        self.baud = baud
        self.hub = hub_ref
        self._ser: serial.Serial | None = None
        self._tx = TargetQueue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.is_open = False
        self.line_ending = b"\n"
        self._rx_buf = bytearray()
        self._exec_engine = ExecEngine()

    def open(self) -> None:
        self._ser = serial.Serial(self.port, self.baud, timeout=0.05)
        self.is_open = True
        self.hub.append_log(self.name, "---", f"opened {self.port} @ {self.baud}", who="system")

    def close(self) -> None:
        self.abort_agent_work()
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        if self._ser:
            try:
                if self._ser.is_open:
                    self._ser.close()
            except Exception:
                pass
        was = self.is_open
        self.is_open = False
        self._ser = None
        if was:
            try:
                self.hub.append_log(self.name, "---", f"closed {self.port}", who="system")
            except Exception:
                pass

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=f"ser-{self.name}", daemon=True)
        self._thread.start()

    def send(self, cmd: str, who: str = "user", raw: bytes | None = None) -> None:
        self._tx.enqueue(cmd, who, raw)

    @property
    def is_busy(self) -> bool:
        return self._tx.is_busy

    def exec(
        self,
        cmd: str,
        prompt: str | None = None,
        prompt_is_regex: bool = False,
    ) -> dict[str, Any]:
        request = self.enqueue_exec(
            cmd,
            prompt=prompt,
            prompt_is_regex=prompt_is_regex,
        )
        return self.wait_exec(request)

    def enqueue_exec(
        self,
        cmd: str,
        prompt: str | None = None,
        prompt_is_regex: bool = False,
    ) -> ExecRequest:
        return self._tx.enqueue_exec(
            self.name,
            cmd,
            prompt=prompt,
            prompt_is_regex=prompt_is_regex,
        )

    def wait_exec(self, request: ExecRequest) -> dict[str, Any]:
        wait_seconds = ExecEngine.TOTAL_SECONDS + ExecEngine.IDLE_SECONDS + 1.0
        if not request.done.wait(wait_seconds):
            request.aborted.set()
            return exec_result(
                self.name,
                ok=False,
                timed_out=True,
                error="Exec wait exceeded total timeout",
            )
        assert request.result is not None
        return request.result

    def abort_agent_work(self) -> None:
        self._tx.abort_agents()

    def _write_request(self, request: WriteRequest) -> bool:
        assert self._ser is not None
        raw = (
            request.raw
            if request.raw is not None
            else request.cmd.encode("utf-8", errors="replace") + self.line_ending
        )
        if not self._tx.write_if_allowed(request, lambda: self._ser.write(raw)):
            return False
        self._ser.flush()
        log_text = request.cmd if request.raw is None else f"[raw] {request.raw.hex(' ')}"
        self.hub.append_log(self.name, ">>>", log_text, who=request.who)
        return True

    def _service_operator_write(self) -> None:
        request = self._tx.next_write()
        if request is None:
            return
        try:
            self._write_request(request)
        finally:
            self._tx.complete(request)

    def _log_rx_chunk(self, chunk: bytes) -> None:
        self._rx_buf.extend(chunk)
        while True:
            split_at = None
            sep_len = 0
            for sep in (b"\r\n", b"\n", b"\r"):
                if sep in self._rx_buf:
                    split_at = self._rx_buf.index(sep)
                    sep_len = len(sep)
                    break
            if split_at is None:
                break
            line = bytes(self._rx_buf[:split_at]).decode("utf-8", errors="replace")
            del self._rx_buf[: split_at + sep_len]
            self.hub.append_log(self.name, "<<<", line)
        if len(self._rx_buf) > 8192:
            self.hub.append_log(
                self.name,
                "<<<",
                bytes(self._rx_buf).decode("utf-8", errors="replace"),
            )
            self._rx_buf.clear()

    def _run(self) -> None:
        assert self._ser is not None
        while not self._stop.is_set():
            try:
                request = self._tx.next_write()
                if request is not None:
                    try:
                        if isinstance(request, ExecRequest):
                            try:
                                request.result = ExecSession(
                                    self.hub,
                                    self._exec_engine,
                                ).execute(
                                    self._ser,
                                    self._tx,
                                    request,
                                    self.line_ending,
                                    on_tx=lambda: self.hub.append_log(
                                        self.name,
                                        ">>>",
                                        request.cmd,
                                        who=request.who,
                                    ),
                                    on_rx=self._log_rx_chunk,
                                    service_operator=self._service_operator_write,
                                )
                            finally:
                                if request.result is None:
                                    request.result = exec_result(
                                        self.name,
                                        ok=False,
                                        error="Exec failed",
                                    )
                                request.done.set()
                        else:
                            self._write_request(request)
                    finally:
                        self._tx.complete(request)

                chunk = self._ser.read(4096)
                if chunk:
                    self._log_rx_chunk(chunk)
                else:
                    time.sleep(0.02)
            except SerialException as e:
                self.hub.append_log(self.name, "---", f"SerialException: {e}", who="system")
                self.is_open = False
                break
            except Exception as e:
                self.hub.append_log(self.name, "---", f"error: {e}", who="system")
                time.sleep(0.2)
