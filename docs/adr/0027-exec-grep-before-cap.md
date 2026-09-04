# Grep Exec output before the 32KiB cap

`serial_exec` accepts optional Grep (`grep`, later `grep_is_regex` / `grep_context`). The Hub applies Grep to the full stripped capture, then applies the existing trailing 32 KiB cap so Agents can find needles that the cap would have dropped and still cannot blow context. `truncated` remains "returned output was clipped"; `match_count` is pre-cap hit rows. Rejected: a new MCP tool, grepping session logs, injecting group separators into `output`, and skipping the cap after a successful Grep.
