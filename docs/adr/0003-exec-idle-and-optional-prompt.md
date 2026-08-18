# Exec completion by idle gap and optional prompt

Agent console use needs a single Exec that returns “the reply,” not fire-and-forget send plus separate tail. Completion is primarily an idle gap (no new serial bytes for a configured interval); an optional prompt pattern may finish earlier when matched. There is no per-Target default prompt — Agents pass `prompt` explicitly when needed. Rejected: prompt-only completion (too brittle across Linux/RTOS) and poll-only send/tail as the primary Agent API.
