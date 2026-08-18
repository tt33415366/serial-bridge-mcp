# Truncate Exec output to last 32KiB

Exec returns at most the last 32 KiB of captured text and sets `truncated: true` when clipped, so Agents cannot blow their context on noisy console dumps. Rejected: no truncation and a smaller 8 KiB cap.
