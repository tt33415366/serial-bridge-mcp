"""Serial port enumeration for Target binding."""
from __future__ import annotations


def _port_order(com: str) -> tuple[str, int, str]:
    """Sort COM2 before COM10 instead of lexicographically."""
    prefix = com.rstrip("0123456789")
    digits = com[len(prefix):]
    return (prefix.upper(), int(digits) if digits else -1, com)


def available_ports() -> list[dict[str, str]]:
    """Enumerate serial ports the Operator can bind a Target to."""
    import serial_bridge.hub as hub

    ports = [
        {
            "com": info.device,
            # Windows descriptions repeat the device, e.g. "USB Serial Port (COM18)".
            "label": (info.description or "").strip().removesuffix(f" ({info.device})"),
        }
        for info in hub.list_ports.comports()
    ]
    return sorted(ports, key=lambda port: _port_order(port["com"]))
