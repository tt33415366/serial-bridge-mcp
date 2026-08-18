# Shared Hub for UI and MCP

The Serial Bridge already has a Web UI that owns COM ports. Agents need MCP access from local Windows and remote Linux without a second process fighting for the same ports. We keep one Hub as the authority; the UI and MCP Server are adapters on that Hub (same process for HTTP MCP; stdio is a thin proxy into it). Rejected: UI-only HTTP wrappers as the long-term Agent API, and an MCP-first rewrite that demotes the UI.
