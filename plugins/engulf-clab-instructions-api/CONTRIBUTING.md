# Contributing

`src/engulf_clab_instructions_api/contract.py` owns the immutable instruction
model and the single invocation-scoped contribution registry. The renderer owns
presentation and lifecycle gating; this API must not print, log, access host
state, or execute contributed commands.

Keep contributions immutable, validate terminal-facing values, and deduplicate
identical entries while preserving callback order. Commands are display-only.
URLs accept only absolute HTTP(S) addresses without embedded credentials. Do
not add topology parsing, persistence, leases, or installation behavior here.

Contributors declare the shared context in both `context_reads` and
`context_writes`. A contribution made in `after_goal()` must be ordered before
`engulf_clab.instructions` through packaging metadata so the renderer sees it.

## Validation

```bash
.venv/bin/ruff check plugins/engulf-clab-instructions-api/src
.venv/bin/mypy --strict plugins/engulf-clab-instructions-api/src
.venv/bin/python -m compileall -q plugins/engulf-clab-instructions-api/src
make build-engulf-clab-instructions-api
```
