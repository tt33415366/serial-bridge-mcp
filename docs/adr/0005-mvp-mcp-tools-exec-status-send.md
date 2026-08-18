# MVP MCP tools include Exec, status, and Send

Primary Agent path is Exec (wait for completion). MVP also exposes Send (no wait) and status (mode/Targets readonly). Tail is deferred. Send exists for cases where the Agent already knows output will arrive later or must not block the tool round-trip; it shares the same per-Target queue as Exec.
