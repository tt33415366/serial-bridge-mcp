# One or two Target Slots

A Hub has one or two Targets; the absent Target does not exist. The Operator adds the second Slot or removes one Slot only in CRT Mode, and the new Target exists only after that add is confirmed. Default remains two Slots (`linux` / `rtos`). Agents still must pass `target`. Env/CLI overlay existing Slots only; persisted `slots[]` length is the count. This supersedes ADR-0020’s “exactly two Slots” and its rejection of add/remove.

## Considered Options

- Disabled twin still listed in status — rejected; a ghost Target Name confuses Agents.
- N-serial — rejected for now; Operator layout and CLI stay 1-or-2.
- Startup-only count — rejected; the Operator already edits Bindings in CRT.
- Optional `target` when count is 1 — rejected; adding a second Target would make omitted `target` a footgun.
- CLI/env grow the count — rejected; count is `slots[]` length, not a second knob.
- Draft add until Save — rejected; Target existence is a Hub fact, not a form draft.

## Consequences

`LINUX_*` / `--rtos-*` remain index aliases (ADR-0020). A one-slot file plus a Slot 1 env/CLI override fails startup. Legacy `ports.{linux,rtos}` still migrates to two Slots. A removed Target’s Session Log stays on disk.
