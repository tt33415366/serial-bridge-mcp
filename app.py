#!/usr/bin/env python3
"""Compatibility entrypoint; prefer `python -m serial_bridge`."""
from serial_bridge.app import main

if __name__ == "__main__":
    main()
