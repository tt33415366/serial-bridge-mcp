# Token on MCP and HTTP write APIs

`SERIAL_BRIDGE_TOKEN` is required for MCP HTTP and for write HTTP APIs (at least command send and mode changes). Read-only status/tail and static UI assets stay open. Binding is `0.0.0.0` on the existing UI port, so unprotected write routes would be LAN-reachable; token on writes closes that gap. How the local Web UI supplies the token is a follow-on decision.
