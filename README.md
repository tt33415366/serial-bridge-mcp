# Serial Bridge

Serial Bridge is a Windows Hub that shares two serial consoles between a local
Operator and MCP Agents. The Hub lives in the `serial_bridge/` package; start
it with `python -m serial_bridge` or the root `app.py` shim.

## Install and start

Python 3.10 or newer is recommended.

```powershell
python -m pip install -r requirements.txt
python -m serial_bridge
```

The Hub opens your browser to the console at `http://127.0.0.1:8765/` once it
is listening. The root `app.py` shim is equivalent. To start without opening a
browser tab:

```powershell
$env:SERIAL_BRIDGE_OPEN_UI = "off"
python -m serial_bridge
```

Or pass `--no-open-ui`. Use `--open-ui` to force open when the environment
disables it. Unset `SERIAL_BRIDGE_OPEN_UI` means open by default; only
`0`, `false`, `no`, and `off` (case-insensitive) disable it.

On first boot the Hub auto-generates an Access Token into `serial_bridge.token`
beside the Port Binding config file (override the path with
`SERIAL_BRIDGE_TOKEN_FILE`). Do not commit the secrets file.

Open **Setup** (`http://127.0.0.1:8765/setup`) on the Hub PC to copy the Hub
URL, view the Access Token, rotate it, and paste a Cursor `mcpServers` snippet.
Setup secrets (token plaintext, Rotate, and the secret-bearing snippet) are
visible only on loopback (`127.0.0.1` / `::1`).

Alternatively, set `SERIAL_BRIDGE_TOKEN` before starting the Hub and give the
same secret to the MCP client. The env var overrides the secrets file for that
process lifetime; Rotate still rewrites the file but warns until env is unset or
the Hub is restarted without it.

MCP authentication is required even from loopback. Do not put the token in source
control, static frontend files, URLs, or logs.

The Hub listens on `0.0.0.0:8765`, so it is reachable from the local network.
Use an appropriate host firewall and a strong token. Remote Agents cannot
change modes or Port Bindings.

## MCP

Use **Setup** (`/setup`) on the Hub PC for a copy-paste Cursor config. Manual
wiring:

Configure the Agent's Streamable HTTP MCP connection with:

```text
URL: http://<hub-host>:8765/mcp
Authorization: Bearer <SERIAL_BRIDGE_TOKEN>
```

Use `/mcp` exactly; the Web UI is at `/`. The MCP Server exposes:

- `serial_status`: read the current mode and each Target's Port Binding,
  open state, and busy hint.
- `serial_exec`: send one text command and capture output until an idle gap,
  an optional prompt match, or the 60-second timeout.
- `serial_send`: send a text line or Raw Payload without waiting for output.

To exercise status and Exec:

1. Open the Web UI locally and switch to **Bridge Mode**.
2. Connect the MCP client to the URL above with the Bearer header.
3. Call `serial_status` with no arguments and confirm `mode` is `bridge` and
   the intended Target is open.
4. Call `serial_exec` with `{"target":"linux","cmd":"uname -a"}` or
   `{"target":"rtos","cmd":"help"}`.
5. If the device has a stable prompt, optionally pass `prompt`; set
   `prompt_is_regex` to `true` only when the prompt value is a regular
   expression.

Exec accepts the Target names `linux` and `rtos`, not COM port names. It
returns captured `output` plus `timed_out`, `truncated`, and `aborted` flags.

Exec output and the `live/*.log` transcripts are plain text with ANSI escapes
removed. The Web UI instead interprets the escapes and shows device colors.

## Port Binding

A Port Binding assigns a Target to a COM port and baud rate. Defaults are
`linux` on `COM3` at 115200 and `rtos` on `COM6` at 115200.

Override defaults before startup with environment variables:

```powershell
$env:SERIAL_BRIDGE_LINUX_PORT = "COM8"
$env:SERIAL_BRIDGE_LINUX_BAUD = "57600"
$env:SERIAL_BRIDGE_RTOS_PORT = "COM9"
$env:SERIAL_BRIDGE_RTOS_BAUD = "115200"
python -m serial_bridge
```

Equivalent CLI flags are `--linux-port`, `--linux-baud`, `--rtos-port`, and
`--rtos-baud`. `SERIAL_BRIDGE_CONFIG` or `--config` selects the persisted JSON
file. The load order is built-in defaults, then environment/CLI values, then
the persisted file; saved Web UI values win.

Only the Operator can edit Port Bindings, and only in **CRT Mode** while the
Hub has released the ports. The Web UI lists the detected serial ports in a
dropdown per Target; use **Scan** to re-enumerate after plugging in an adapter.
Changes made in the Web UI persist for restart.

## Live Directory

The Live Directory is where the Hub writes per-Target Bridge session logs and
`bridge_status.json`. The default is `<app-dir>/live/` beside the project root (same directory as
`serial_bridge.json` and the root `app.py` shim).

Override before startup with:

```powershell
$env:SERIAL_BRIDGE_LIVE_DIR = "D:\logs\serial-bridge"
python -m serial_bridge
```

Or pass `--live-dir`. Load order matches Port Binding: built-in default, then
environment/CLI, then the persisted config file; Web UI saves win.

Each time the Operator enters **Bridge Mode**, the Hub creates fresh log files
named `<TargetName>-YYYY-MM-DD-HHMMSS.log` (local time, 24-hour clock). A second
Bridge session creates new files; older logs are left in place and are not
migrated when you change the Live Directory or rename a Target.

Edit the Live Directory in the Web UI Bindings panel in **CRT Mode** only (same
loopback-only write path as Port Binding). The footer shows the configured
directory and current session log filenames when assigned.

## Bridge Mode and CRT Mode

- **Bridge Mode:** the Hub owns the configured serial ports. The Operator and
  Agents can send commands and observe the same live transcripts.
- **CRT Mode:** the Hub releases the ports for SecureCRT or another exclusive
  serial client. MCP Exec and Send fail until the Operator returns to Bridge
  Mode.

Disconnect SecureCRT before entering Bridge Mode. Switching to CRT Mode aborts
an in-flight Exec and may return partial output.

## Raw Send warning

`serial_send` with `raw_hex` writes arbitrary bytes without text-line framing
or an automatic line ending. This is full console power: control bytes can
interrupt boot, terminate processes, alter device state, or make a session
unresponsive. Prefer `serial_exec` for commands, and use Raw Payloads only
when the exact byte sequence and device impact are understood.
