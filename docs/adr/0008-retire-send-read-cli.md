# Retire send.py and read.py

Once MCP Exec/Send/status exist, the CLI helpers are removed rather than kept as parallel Agent APIs. Agents use MCP; Operators use the Web UI. Rejected: keeping thin HTTP CLIs indefinitely (extra surface, docs drift).
