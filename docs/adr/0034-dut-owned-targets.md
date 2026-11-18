# A Hub owns many DUTs

One Hub serves many DUTs. A DUT owns one or two Targets and its own Bridge or CRT Mode, so one board can sit in SecureCRT while another stays in Bridge. Agents address a console by DUT Name and Target Name, both always required, and a Target Name is unique only within its DUT. This supersedes ADR-0030's rejection of more than two Targets, ADR-0033's Hub-wide mode switch, and ADR-0024's rule that the Live Directory changes only in CRT Mode.

## Considered Options

- More Targets and no DUT — rejected; `linux` would have to be unique on the whole Hub, and the board would be invisible to Agents.
- One Hub process per DUT — rejected; the boards share one Hub.
- Hub-wide Bridge/CRT — rejected; releasing every board so one can be opened in SecureCRT couples the boards.
- Live Directory editable only when every DUT is in CRT — rejected; that couples unrelated boards.
- Optional `dut` when only one DUT exists — rejected; the same footgun ADR-0030 rejected for `target`.

## Consequences

A file that still has top-level `slots` or `ports` loads as one DUT named `dut`, titled DUT. Env and CLI overlay that first DUT only. Each DUT starts in CRT Mode and mode is not saved. Session logs are `<DutName>-<TargetName>-YYYY-MM-DD-HHMMSS.log`. Agent Trace, mode, and in-flight Exec checks are per DUT. `serial_status` is not an Agent Trace entry.
