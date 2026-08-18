# Target COM port and baud are configurable

Default Targets remain named `linux` and `rtos`, but each Target’s COM port and baud come from configuration rather than hard-coded COM3/COM6. Sources: environment variables and CLI overrides at startup, plus Web UI edits that persist to a config file. Agent tools keep using Target names; Operators change bindings via env/UI. Rejected: env-only (no UI persistence) and config-file-only without env.

Status: accepted; Target Name configurability is extended by ADR-0020 (two fixed Target Slots with editable names/titles). Port/baud configuration here still stands.
