# Serial Bridge

Serial Bridge is a Hub that shares one or two serial consoles between a local Operator
and MCP Agents. It is not OS-specific: install the Python packages in
`requirements.txt` and run it on any host with Python 3.10+. The Hub lives in
the `serial_bridge/` package; start it with `python -m serial_bridge` or the
root `app.py` shim.

## Install and start

Python 3.10 or newer is recommended.

```powershell
python -m pip install -r requirements.txt
python -m serial_bridge
```

Shell snippets below use PowerShell (`$env:NAME = "..."`). On bash or zsh, set the
same names with `export NAME=...`.

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

Open **Setup** (`http://127.0.0.1:8765/setup`) on the Hub host to copy the Hub
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

Use **Setup** (`/setup`) on the Hub host for a copy-paste Cursor config and a
short Cursor rule ("Agent guide") that teaches the Agent the token-saving Exec
options below. Manual wiring:

Configure the Agent's Streamable HTTP MCP connection with:

```text
URL: http://<hub-host>:8765/mcp
Authorization: Bearer <SERIAL_BRIDGE_TOKEN>
```

Use `/mcp` exactly; the Web UI is at `/`. The MCP Server exposes:

- `serial_status`: read the current mode and each Target's Port Binding,
  open state, busy hint, and current Session Log (`log` is the filesystem
  path on the Hub host; `log_url` is a relative Bearer GET of that file from
  the same origin as `/mcp`). Empty `log` / `log_url` means none assigned.
  Last N lines are `serial_tail`, not Exec output. Do not pull the Session Log
  into `serial_exec` output.
- `serial_exec`: send one text command and capture output until an idle gap,
  an optional prompt match, or the 60-second timeout. The device's Echo of the
  command and the matched prompt text are removed from `output`; the Session
  Log keeps both. Options:
  - `prompt` / `prompt_is_regex`: end early when the prompt appears.
    `prompt_settle_ms` (0–999, default 0) is a Settle Window: after the prompt
    matches, keep capturing until the device is quiet for that long, for
    consoles that print the prompt before the command's output.
  - `exit_code: true`: Exit Code Probe for POSIX shell Targets. The Hub wraps
    the command so the shell prints `$?` behind a one-time token, removes that
    trailer, and reports `exit_code` (an integer, or `null` when the trailer
    never arrived and the Exec ended by idle). Cannot be combined with
    `prompt`; works with `grep`.
  - `grep` / `grep_is_regex` / `grep_context`: keep only matching lines (plus
    neighbors). `grep_invert: true` keeps the non-matching lines instead;
    `match_count` is always the number of matching lines. `grep_invert` and
    `grep_context` are mutually exclusive.
  - `max_lines`: keep only the last N lines after Grep; `lines_dropped`
    reports how many were cut.
- `serial_send`: send a text line or Raw Payload without waiting for output.
- `serial_tail`: read one Target's last `n` lines of the current Session Log
  (default 40, max 200); result `{ok, target, tail, n}`. Each line is reduced
  to direction (`<<<` rx, `>>>` tx, `---` system) and text; pass
  `with_timestamps: true` to prefix `HH:MM:SS.mmm`. The whole file remains
  `log_url`.

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

Exec accepts the Target names `linux` and `rtos`, not serial device names. The
result is `{ok, output}`; `truncated`, `timed_out`, and `aborted` appear only
when true, and `error` only on failure. `ok` means the capture finished
(prompt or idle), not that the remote command succeeded — use `exit_code` for
that on shell Targets. `truncated` is only the trailing 32KiB cap, not an
early prompt match. On Target `linux`, do not use a short shell prompt such as
`#` as `prompt`: a literal `#` matches comments and ends Exec early.

Exec output and the `live/*.log` transcripts are plain text with ANSI escapes
removed. The Web UI instead interprets the escapes and shows device colors.

The **Agent Trace** in the Web UI lists every Exec, Send, Tail, and status read
with the bytes each returned to the Agent, and its footer shows the running
total for this Hub session. Compare that total across the same device task
before and after changing how the Agent calls the tools.

## Port Binding

A Port Binding assigns a Target to a serial device path and baud rate.
Built-in defaults are Windows-style (`linux` on `COM3`, `rtos` on `COM6`, both
115200); on Linux or macOS set paths such as `/dev/ttyUSB0` instead.

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

The persisted config file holds an ordered `slots` array. A persisted `slots` array of
length 1 is valid and is the count. In **CRT Mode** the Operator may add a second
Target or remove one Target.

`SERIAL_BRIDGE_RTOS_PORT`, `SERIAL_BRIDGE_RTOS_BAUD`, `--rtos-port`, `--rtos-baud`,
`SERIAL_BRIDGE_SLOT1_PORT`, and `SERIAL_BRIDGE_SLOT1_BAUD` refer to Target Slot 1. When
the persisted file defines only one Slot, those env/CLI overrides fail startup; the
error states that the override refers to Target Slot 1 but only one Slot is configured.

Only the Operator can edit Port Bindings, and only in **CRT Mode** while the
Hub has released the ports. The Web UI lists the detected serial ports in a
dropdown per Target; use **Scan** to re-enumerate after plugging in an adapter.
Changes made in the Web UI persist for restart.

## Live Directory

The Live Directory is where the Hub writes per-Target Bridge session logs and
`bridge_status.json`. The default is `<app-dir>/live/` beside the project root
(same directory as `serial_bridge.json` and the root `app.py` shim).

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
directory and current session log filenames when assigned. Click a current
Session Log filename to reveal it in the host file manager (Hub host /
loopback). Download the current file with
`GET /api/session-log?target=<TargetName>` (loopback or
`Authorization: Bearer`, advertised as `log_url` on each Target in
`serial_status`). Click does not download.

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
