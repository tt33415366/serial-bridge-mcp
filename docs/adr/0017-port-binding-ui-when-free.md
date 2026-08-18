# Port Binding edits only while ports are free

Operators may change Target COM/baud in the Web UI only when it is safe for the Hub to rebind — effectively while in CRT Mode (ports released), or by requiring a CRT transition around the change. Agents cannot change Port Bindings. Startup merges defaults, env/CLI, then the persisted config file (file wins for UI-saved values).
