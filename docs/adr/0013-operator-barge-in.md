# Operator input may barge ahead of the Agent queue

When the Operator types in the Web UI, their write is prioritized ahead of queued Agent Exec/Send work on that Target. An in-flight Exec keeps capturing RX (and may be disturbed by the barged write). Rejected: strict shared FIFO with the Operator, and locking the UI while an Exec runs.
