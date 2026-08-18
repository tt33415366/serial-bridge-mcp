# Raw/hex only on Send; Exec stays text lines

Control bytes (e.g. Ctrl-C) go through Send with optional raw/hex. Exec always sends a text line with the configured line ending, then captures until idle and/or optional prompt. Rejected: raw on Exec, and a separate write_raw tool for MVP.
