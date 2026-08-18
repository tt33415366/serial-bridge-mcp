"""ANSI stripping, display sanitization, and transcript timestamps."""
from __future__ import annotations

import re
from datetime import datetime

ANSI_RE = re.compile(r"\x1b(?:\][^\x07]*(?:\x07|\x1b\\)|[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
# Control bytes that would silently vanish in a browser or corrupt the log file.
_LOG_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_DISPLAY_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1a\x1c-\x1f\x7f]")


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def strip_ansi(text: str) -> str:
    """Plain text: no escape sequences and no stray control bytes."""
    return _LOG_CONTROL_RE.sub("", ANSI_RE.sub("", text))


def sanitize_display(text: str) -> str:
    """Keep escape sequences so the Web UI can colorize; drop other controls."""
    return _DISPLAY_CONTROL_RE.sub("", text)
