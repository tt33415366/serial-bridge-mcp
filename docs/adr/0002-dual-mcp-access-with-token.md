# Dual MCP access with token-authenticated HTTP

Agents run either on the same Windows PC as the Hub or on a remote Linux machine where the code lives. MVP exposes MCP over authenticated HTTP (Access Token) on the LAN (same port as the UI). Local stdio proxy is deferred; local Agents use HTTP to loopback for now. Rejected: loopback-only MCP plus mandatory SSH tunnels as the sole remote path (safer but rejected for day-to-day convenience).
