# Configurable Live Directory Design

Date: 2026-08-18  
Status: Approved for implementation planning  
Glossary: [`CONTEXT.md`](../../../CONTEXT.md)  
Parent: [`2026-08-18-serial-bridge-mcp-design.md`](./2026-08-18-serial-bridge-mcp-design.md)

## Problem

The Hub hardcodes transcript storage under `C:\courtolab\CRT_LOG\live` as `{TargetName}.log`. Operators on other machines (or who want Hub-local storage) cannot change that path without editing source. Session logs also overwrite/append the same fixed filename across Bridge sessions, making it hard to find “this Bridge run.”

## Goals

- Make the **Live Directory** configurable via defaults → env/CLI → persisted config (**file wins** for UI-saved values), matching Port Binding.
- Default Live Directory to **`<app-dir>\live\`** (directory containing the Hub entrypoint), not `C:\courtolab\...`.
- On each **CRT → Bridge** transition, create a new per-Target log file named  
  `<TargetName>-<YYYY-MM-DD>-<HHMMSS>.log` (local time, 24h clock, no colons).
- Edit Live Directory only in **CRT Mode**; apply the new directory when entering Bridge (no Hub process restart required).
- Do **not** migrate old log files when the directory or Target Name changes.
- Expose Live Directory and each Target’s **current session log path** via status (UI + `serial_status`).

## Non-goals

- Per-Target absolute log path overrides.
- Automatic copy/move of historical logs.
- Calendar-day rotation while staying in Bridge.
- Agent/MCP mutation of Live Directory.
- Changing Access Token / secrets file location (unchanged).

## Decisions (locked)

| Topic | Choice |
|--------|--------|
| Scope | Single Live Directory for all Target logs + `bridge_status.json` |
| Config sources | Built-in default → env/CLI → config file (file wins) |
| Default path | `Path(__file__).resolve().parent / "live"` |
| Edit gate | CRT Mode only (same panel as Port Binding) |
| Apply timing | Next entry into Bridge Mode; no migration of old files |
| Filename | `<name>-YYYY-MM-DD-HHMMSS.log` at Bridge start |
| Status | `serial_status` includes `live_dir` and per-Target current `log` path |

## Architecture

```text
Config
  slots[] (existing)
  live_dir: Path   ← NEW

Hub
  start_bridge():
    ensure live_dir exists
    for each Target: assign ports[name].log = live_dir / f"{name}-{date}-{time}.log"
    open PortWorkers; append_log writes to that path for this Bridge session
  stop / CRT:
    close workers; keep last log path in status until next Bridge
  bridge_status.json → always under current live_dir
```

### Config shape

`serial_bridge.json` gains a top-level string field:

```json
{
  "live_dir": "D:\\SourceCode\\serial_bridge\\.worktrees\\serial-bridge-mcp\\live",
  "slots": [ ... ]
}
```

- Missing `live_dir` → use merge result of default + env/CLI (no forced rewrite until Operator saves).
- Relative paths resolve against the Hub app directory (same directory as `DEFAULT_CONFIG_PATH`), then normalize to absolute for status/UI.
- Invalid/unusable path on save: reject with clear error; keep prior value.
- On Bridge start, if `mkdir` fails: fail entering Bridge with status/UI error (same class as serial open failure).

### Env / CLI

- `SERIAL_BRIDGE_LIVE_DIR`
- `--live-dir` (CLI overrides env for that process start; persisted file still wins when present after UI save — same load-order rule as slots)

### Hub log path lifecycle

1. **CRT / idle:** `ports[name]["log"]` may be unset or point at the previous Bridge session’s file for status/tail.
2. **Entering Bridge:** for each Target, set  
   `log = live_dir / f"{name}-{YYYY-MM-DD}-{HHMMSS}.log"`  
   using local time at session start. Prefer one shared timestamp for both Targets in the same transition so a dual-Target Bridge session is easy to correlate.
3. **During Bridge:** all `append_log` for that Target append to that file.
4. **Rename / live_dir change in CRT:** update config only; do not rename or move files. Next Bridge creates new files under the new name/directory.
5. **`/api/tail`:** reads the Target’s **current** `log` path if the file exists; otherwise empty. Does not search historical files.

### Web UI

- Binding panel (CRT): text field for Live Directory; saved with bindings/slots persistence.
- Footer / status: show Live Directory and, when known, current session log filename(s).
- README: document default `<app-dir>\live\`, env, Bridge-session naming, no migration.
- gitignore the default `live/` directory contents (or the directory) so session logs are not committed.


### MCP / status

`serial_status` (and Hub `status()` used by UI) includes:

- `live_dir`: absolute path string
- per Target: existing fields plus `log` (absolute path of current session file, or empty/null if none since last Bridge)

Agents remain read-only for this.

## Error handling

| Situation | Result |
|-----------|--------|
| Corrupt/missing `live_dir` in file | Fall back to default+env; warn in status |
| Live Directory not creatable on Bridge enter | Stay CRT / fail Bridge enter; surface error |
| Invalid path on UI save | Reject save; keep prior config |
| Old courtolab logs | Left in place; not auto-imported |

## Testing

1. Config merge: default app-dir `live` → env → file wins; relative path resolution.
2. Hub: entering Bridge creates `name-YYYY-MM-DD-HHMMSS.log` under configured `live_dir`; second Bridge creates a new distinct file.
3. Changing `live_dir` in CRT does not move old files; next Bridge writes under the new directory.
4. Target rename: next Bridge uses new name in filename; old log remains.
5. Status exposes `live_dir` and per-Target `log`.
6. UI/API: Live Directory editable only in CRT; loopback-only write (same as bindings).

## ADR

- 0024 Configurable Live Directory + Bridge-session log filenames

## Deferred

- Log retention / cleanup UI.
- Selecting historical log files in the UI for replay.
