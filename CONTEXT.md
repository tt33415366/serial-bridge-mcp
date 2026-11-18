# Serial Bridge

Local Windows service that owns device console serial ports so a human Operator and remote/local Agents can share the same live consoles while source code may live on another machine.

## Language

**Hub**:
The single in-process authority that owns every DUT, the serial ports, and the live console transcript.
_Avoid_: bridge process, backend, server (ambiguous with MCP Server)

**DUT**:
One unit under test on the Hub. It owns one or two Targets and its own Bridge or CRT Mode; a Target belongs to exactly one DUT, a Hub has one or more, and a new DUT enters existence in CRT Mode, a DUT is removed only while it is in CRT Mode, and the last DUT cannot be removed.
_Avoid_: pair, device, board

**DUT Name**:
The Agent-facing identifier string for a DUT (`^[a-z][a-z0-9_]{0,31}$`, unique among the Hub's DUTs, stored lowercase). The Web UI derives it from that DUT's Display Title instead of showing its own field, so it changes only while that DUT is in CRT Mode. The Hub's initial DUT is named `dut`.
_Avoid_: name (alone), id (too generic), target

**Target**:
A console endpoint of one DUT, identified by a configurable Agent-facing **Target Name** (defaults `linux` and `rtos`), bound to a COM port and baud. Agents address it by its DUT Name and Target Name, not by COM number.
_Avoid_: port (alone), device, channel, interface, DUT, COM3/COM6 as primary names in Agent APIs

**Target Name**:
The Agent-facing identifier string for a Target (`^[a-z][a-z0-9_]{0,31}$`, unique among that DUT's Target Slots, stored lowercase). The Web UI derives it from the Display Title instead of showing its own field, so it changes only while its DUT is in CRT Mode.
_Avoid_: name (alone), id (too generic), key (implementation jargon)

**Display Title**:
The Operator-facing label for a DUT or a Target, distinct from DUT Name and Target Name. The initial DUT's title is “DUT”; Target defaults are “Linux” and “RTOS”. Trim length 1–64, editable only while that DUT is in CRT Mode because the derived name follows it. A DUT title is rejected when the derived DUT Name belongs to another DUT; a Target title is rejected when that DUT's Slots would derive the same Target Name.
_Avoid_: name (alone — ambiguous with DUT Name and Target Name), label (vague), title (alone)

**Target Slot**:
A position on a DUT that holds one Target’s name, Display Title, and Port Binding. A DUT has one or two Slots; the Operator adds or removes the second only while that DUT is in CRT Mode, and the new Target exists only after that add is confirmed.
_Avoid_: channel index, port index (sounds like COM), serial interface

**Port Binding**:
The Operator-facing assignment of a Target to a COM port and baud, persisted in the config file. Environment and CLI overlay only the first DUT in that file's order, and only Slots that already exist. The Web UI can change a DUT's bindings only while that DUT is in CRT Mode. A COM port belongs to at most one Target on the Hub.
_Avoid_: port config (vague), device map

**Live Directory**:
The single directory where the Hub writes Bridge-session Target log files and `bridge_status.json`, defaulting beside the Hub app (`<app-dir>\live\`). Changing it is allowed while a DUT is in Bridge Mode; each DUT uses the new directory on its next entry into Bridge Mode, and a DUT already in Bridge Mode keeps writing its current Session Log.
_Avoid_: log path (alone — ambiguous with a single file), CRT_LOG, transcript root (jargon)

**Session Log**:
The complete on-disk record of one Target for one entry of its DUT into Bridge Mode, written under the Live Directory as `<DutName>-<TargetName>-YYYY-MM-DD-HHMMSS.log`. The live transcript view and Exec output are bounded subsets of it, not replacements.
_Avoid_: saved logs file, log file (alone), transcript (the live view)

**Tail**:
A bounded snapshot of the last N lines of the current Session Log, each reduced to direction and text (the time only on request; the date and Target title are never repeated).
_Avoid_: Follow (the Operator pane pin), session log (the whole file), transcript (the live view), live tail (English in Follow, not this term)

**Bridge Mode**:
A DUT's mode in which the Hub holds that DUT's serial ports open. Operator and Agent may both send and observe those streams. Other DUTs are unaffected.
_Avoid_: agent mode, connected mode

**CRT Mode**:
A DUT's mode in which the Hub has released that DUT's serial ports so SecureCRT (or another exclusive client) can own them. Other DUTs are unaffected, every DUT is in CRT Mode when the Hub starts, and mode is not persisted.
_Avoid_: disconnected, idle, released (as the mode name)

**Operator**:
The human at the local Web UI.
_Avoid_: user (ambiguous with OS user), human (as an API who-value when `operator` is clearer)

**Focused DUT**:
The DUT a browser page is showing: its Target panes and its Agent Trace. Each page remembers its own. The Hub has no single focused DUT.
_Avoid_: current DUT (sounds like Hub state), selected device

**Command History**:
Per-DUT, per-Target recall of text the Operator submitted from that pane’s composer (not Agent Exec/Send). Prefix of the current input selects newer-to-older matches; empty input walks the full list; Down restores the draft. Persists in the browser for that Operator, including while another DUT is on screen.
_Avoid_: transcript (that is the live console log), shell history (implies a local OS shell)

**Agent**:
An LLM client driving the Hub through MCP (`who=agent` on the transcript).
_Avoid_: AI, bot, Cursor (product-specific)

**Exec**:
One Agent request that sends a command to a Target and returns the captured device output until completion (idle gap and/or optional prompt).
_Avoid_: run, shell (implies a local OS shell), send (see Send)

**Echo**:
The device's own repetition of the command text at the start of an Exec capture, with or without a leading device prompt. The Hub drops it from Exec output; the Session Log keeps it.
_Avoid_: header line, first line (positional, not a concept), command line (ambiguous with the command itself)

**Settle Window**:
An optional quiet period after an Exec's prompt matches: capture continues until no device output arrives for that long, so results a device prints after its prompt are still included. Zero means the prompt match ends the Exec at once.
_Avoid_: grace period (vague), post-prompt idle (conflates with the idle gap that ends an unprompted Exec), delay (implies waiting before sending)

**Exit Code Probe**:
An opt-in Exec on a shell Target where the Hub wraps the command so the device prints its exit status behind a one-time token, then removes that trailer from the output and reports the exit code separately. A null exit code means the trailer never arrived; the Exec itself still completes by idle.
_Avoid_: checked wrap (the retired Agent-side recipe), status line (ambiguous with serial_status), return code (fine in shell docs, but the API field is exit code)

**Grep**:
An optional post-capture narrowing on one Exec: after capture completes, retain only lines matching a pattern (literal substring by default, or a regular expression when opted in), plus any requested neighboring lines around each match; or, when inverted, drop the matching lines and retain the rest. The Agent receives that subset as output, not the full capture.
_Avoid_: filter (vague), search (vague), Tail (the last-N Session Log snapshot), keyword (the contract is one pattern, like prompt)

**Send**:
One Agent request that writes a command to a Target and returns immediately without waiting for device output.
_Avoid_: fire-and-forget (jargon), exec (implies waiting)

**Agent Trace**:
The Operator-facing list belonging to one DUT for this Hub session: that DUT's Agent Exec, Send, and Tail, the bytes each returned, and that DUT's running total. The screen shows the focused DUT's list. A status read that names no DUT is not an entry. Each DUT's list remains while another DUT is on screen, and is dropped when the Hub restarts.
_Avoid_: hub-wide feed, spine (layout jargon), activity feed, agent history (sounds durable across Hub restarts), exec log

**Trace Jump**:
The Operator action of selecting an Exec entry in the focused DUT's Agent Trace to scroll to and briefly highlight that Exec’s capture in that same DUT's live transcript. The pane materializes the capture if needed; the jump succeeds while at least one of its lines remains retained, and misses only after all capture lines leave retention (or none existed).
_Avoid_: clickable trace (UI-only phrasing), jump to log (ambiguous with session log files), replay (implies re-running)

**Transcript Gap**:
A placeholder in a Target’s live pane for consecutive transcript lines that exist in the session log but were not materialized in the current view.
_Avoid_: omitted lines (as the concept name), skipped logs, ellipsis (UI chrome)

**Follow**:
Whether an on-screen Target pane is pinned to the live tail; leaving the tail pauses materializing new lines into the view. When that browser leaves the DUT, those panes are dropped, and showing the DUT again starts pinned to the tail.
_Avoid_: auto-scroll (implementation), stick (vague), tail mode (jargon)

**Live View Budget**:
The Operator-chosen cap, shared by the on-screen Target panes of the focused DUT, on retained transcript entries available to virtual history, including Transcript Gap markers. Tightening it drops the oldest retained entries. Leaving the DUT in that browser drops the retained entries. Neither changes the complete session log. DOM materialization is a separate bounded virtual window that limits how many entries render at once.
_Avoid_: max term lines, scrollback (alone — sounds like the session log), buffer size

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

**Mode Switch Permission**:
The Operator-controlled Web UI setting, one per Hub and off by default, that lets an Agent switch a named DUT's Bridge or CRT Mode through MCP. Agent-facing status reports whether it is granted and what the Agent should do next. It never covers Port Binding or port discovery. An in-flight Exec on the named DUT refuses the switch; another DUT's Exec does not. It never lets an Agent interrupt an in-flight Exec.
_Avoid_: agent mode, auto-switch, unlock

**Port State**:
Per-Target fact about the Hub's hold on its serial port: closed, open, or lost (the port was open and then dropped). It is independent of mode, busy, and Shell Readiness; Bridge Mode does not imply every Target is open.
_Avoid_: accessible, connected (ambiguous with mode), online

**Shell Readiness**:
Per-Target, per-Bridge-session claim that the device shell is at its prompt, reported ready only while a fresh observation matches the Target Prompt and unknown otherwise (including when none is configured). A send, reconnect, a change of its DUT's mode, or a lost port clears it; the Hub never sends a probe to establish it.
_Avoid_: not ready (this version never asserts it), alive, responsive

**Exec Status**:
How one Exec ended: completed (prompt or Exit Code Probe evidence; a nonzero exit code is still completed), quiet (output went idle without completion evidence), timeout (observation window expired), disconnected (the port was lost mid-Exec, partial capture kept), aborted (the Operator or a mode change cut it short), or error (internal or protocol failure). Quiet and timeout end observation only; they do not show the command finished and never justify an automatic resend.
_Avoid_: result (alone), state (ambiguous with Port State), ended_by (the detail field behind it)

**Raw Capture**:
The first 32 KiB (counted before encoding) of the unmodified bytes received from a Target during one Exec's capture window, returned only on request as Base64 and flagged when truncated. It is independent of Grep and line limits, keeps wrapper, end marker and ANSI bytes exactly as received, and can include bytes the command did not produce.
_Avoid_: raw log (sounds like the Session Log), output (alone, the cleaned form)

**Target Prompt**:
The Operator-configured pattern (a regular expression) for a Target's shell prompt, used only to judge Shell Readiness. An invalid pattern is rejected, and changing it clears that Target's readiness. An Exec's own prompt argument applies to that Exec alone and never alters it.
_Avoid_: prompt (alone, ambiguous with the per-Exec argument), shell pattern
