# Single main entry app.py; retire parallel entrypoints

The Hub+UI+MCP HTTP surface lives in the `app.py` line (plus extracted Hub/MCP modules as needed). `bridge.py`, `gui_app.py`, `send.py`, and `read.py` are removed from the main path to stop API drift. Rejected: keeping overlapping entrypoints with “legacy” labels.
