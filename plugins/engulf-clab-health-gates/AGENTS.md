# Plugin Instructions

`engulf-clab-health-gates` waits for explicitly declared service endpoints only
after a successful `deploy`. It must never perform network activity in
`analyze_call()`. Configuration is read from the shared original topology
session, and diagnostics are emitted through the callback-bound logger.

Plugin ID: `engulf_clab.health_gates`
