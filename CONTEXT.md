# Serial Bridge

Local Windows service that owns device console serial ports so a human Operator and remote/local Agents can share the same live consoles while source code may live on another machine.

## Language

**Hub**:
The single in-process authority that owns serial ports, mode, and the live console transcript.
_Avoid_: bridge process, backend, server (ambiguous with MCP Server)

**Target**:
A console endpoint identified by a configurable Agent-facing **Target Name** (defaults `linux` and `rtos`), each bound to a COM port and baud. Exactly two Targets exist in MVP; Agents address a Target by Target Name, not by COM number.
_Avoid_: port (alone), device, channel, COM3/COM6 as primary names in Agent APIs

**Target Name**:
The Agent-facing identifier string for a Target (`^[a-z][a-z0-9_]{0,31}$`, unique across Target Slots, stored lowercase). The Web UI derives it from the Display Title instead of showing its own field, so it changes only in CRT Mode.
_Avoid_: name (alone), id (too generic), key (implementation jargon)

**Display Title**:
The Operator-facing label for a Target in the Web UI (defaults “Linux” / “RTOS”), distinct from Target Name; trim length 1–64; editable only in CRT Mode because the Target Name follows it, and rejected when two Slots would derive the same Target Name.
_Avoid_: name (alone — ambiguous with Target Name), label (vague), title (alone)

**Target Slot**:
One of the two fixed MVP positions that hold a Target’s name, Display Title, and Port Binding; slots are not created or deleted by the Operator.
_Avoid_: channel index, port index (sounds like COM)

**Port Binding**:
The Operator-facing assignment of a Target to a COM port and baud, loaded from environment/CLI and editable in the Web UI with persistence to a config file.
_Avoid_: port config (vague), device map

**Live Directory**:
The single directory where the Hub writes Bridge-session Target log files and `bridge_status.json`, defaulting beside the Hub app (`<app-dir>\live\`), configurable like Port Binding, and applied on the next entry into Bridge Mode.
_Avoid_: log path (alone — ambiguous with a single file), CRT_LOG, transcript root (jargon)

**Bridge Mode**:
Hub holds the serial ports open; Operator and Agent may both send and observe the same streams.
_Avoid_: agent mode, connected mode

**CRT Mode**:
Hub has released the serial ports so SecureCRT (or another exclusive client) can own them.
_Avoid_: disconnected, idle, released (as the mode name)

**Operator**:
The human at the local Web UI.
_Avoid_: user (ambiguous with OS user), human (as an API who-value when `operator` is clearer)

**Command History**:
Per-pane recall of text the Operator submitted from that pane’s composer (not Agent Exec/Send). Prefix of the current input selects newer-to-older matches; empty input walks the full list; Down restores the draft. Persists in the browser for that Operator.
_Avoid_: transcript (that is the live console log), shell history (implies a local OS shell)

**Agent**:
An LLM client driving the Hub through MCP (`who=agent` on the transcript).
_Avoid_: AI, bot, Cursor (product-specific)

**Exec**:
One Agent request that sends a command to a Target and returns the captured device output until completion (idle gap and/or optional prompt).
_Avoid_: run, shell (implies a local OS shell), send (see Send)

**Send**:
One Agent request that writes a command to a Target and returns immediately without waiting for device output.
_Avoid_: fire-and-forget (jargon), exec (implies waiting)

**Agent Trace**:
The Operator-facing list, in the Bridge console, of this Hub session’s Agent Exec and Send activity used for at-a-glance supervision.
_Avoid_: spine (layout jargon), activity feed, agent history (sounds durable across Hub restarts)

**Trace Jump**:
The Operator action of selecting an Agent Trace Exec entry to scroll to and briefly highlight that Exec’s capture in the Target’s live transcript, only when that capture is still present in the current view.
_Avoid_: clickable trace (UI-only phrasing), jump to log (ambiguous with session log files), replay (implies re-running)

**Raw Payload**:
Bytes written to a Target without the usual text-line framing (for example hex-encoded Ctrl-C), as an opt-in alternative to a normal text line.
_Avoid_: binary mode (sounds like a session mode), unescaped (vague)

**MCP Server**:
The Hub-facing tool surface (authenticated HTTP in MVP; stdio proxy later) that exposes Exec, Send, and status to Agents.
_Avoid_: calling the whole product “the MCP”; the Hub is the product core

**Access Token**:
Shared secret required for MCP HTTP and for non-loopback `POST /api/send`. Generated once on first Hub boot into a secrets file (not the Port Binding config file), overridable by environment for the process lifetime, and rotatable from the local Setup Page; loopback UI traffic is exempt; mode changes remain loopback-only.
_Avoid_: password, API key (unless matching a specific header name in docs)

**Setup Page**:
The local Web UI route that guides the Operator to wire an Agent’s MCP client (URL, Bearer Access Token, copy-paste client config) and to rotate the Access Token.
_Avoid_: settings page (too broad), onboarding (implies first-run wizard only)

**Open UI**:
Whether the Hub launches the Operator’s browser to the local console (`http://127.0.0.1:8765/`) after it is listening; on by default, switched only via environment or CLI.
_Avoid_: auto-open (vague), startup page (sounds like Setup Page)
