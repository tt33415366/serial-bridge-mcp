# Loopback exemption for write HTTP APIs

Non-loopback clients must present `SERIAL_BRIDGE_TOKEN` for MCP and for `POST /api/send`. Requests from `127.0.0.1`/`::1` are exempt so the local Web UI keeps working without embedding the token in static JS. `POST /api/mode` is loopback-only (remote Agents must not switch Bridge/CRT). Rejected: injecting the token into the browser via a special local-config endpoint, and requiring tokens on all UI calls.
