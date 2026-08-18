# Bearer token for MCP and non-loopback send

Clients present `Authorization: Bearer <SERIAL_BRIDGE_TOKEN>` for MCP HTTP and for non-loopback `POST /api/send`. Rejected: custom `X-Serial-Bridge-Token` header and query-string tokens.
