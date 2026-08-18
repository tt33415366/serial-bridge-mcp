# Open UI after listen, env/CLI only

The Hub opens the Operator browser to `http://127.0.0.1:8765/` by default once it is listening. Disable with `SERIAL_BRIDGE_OPEN_UI` set to `0`/`false`/`no`/`off` (case-insensitive) or `--no-open-ui`; unset env means open. Operators start the Hub with `python -m serial_bridge` (or the root `app.py` shim); legacy Windows launcher scripts are removed so Open UI has a single owner. Open failure is a warning, not a process exit. Rejected: persisting this in the config file or Web UI, opening Setup instead of the console, and opening before listen.
