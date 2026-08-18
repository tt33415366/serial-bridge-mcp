# MCP may observe mode but not change it

Bridge Mode vs CRT Mode is a physical ownership choice (SecureCRT vs Hub). Letting Agents flip mode would silently yank ports from the Operator’s CRT session. MCP can read status (mode, Targets, open flags) but must not switch mode; the Operator switches via the Web UI only.
