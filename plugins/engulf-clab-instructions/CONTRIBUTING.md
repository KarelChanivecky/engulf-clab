# Contributing

`src/engulf_clab_instructions/plugin.py` owns topology env extraction, removal
from the writer's derived topology, success gating, and output formatting. The
lab parser owns source selection, environment expansion, inheritance, and the
invocation-scoped `TOPOLOGY_CONTEXT`; do not parse a second copy of the source.

The renderer reads the instruction API's immutable registry during `after_goal`.
Providers publish through `record_instruction()` and declare the shared context
in both reads and writes. A provider that writes in `after_goal()` must place
`engulf_clab.instructions` after itself with a packaging dependency edge. Keep
the renderer's topology preparation after the parser and before the writer, as
declared in this package's dependency entry points.

Only a completed deploy or redeploy with exit code zero is considered successful.
Use the callback-bound logger for output. Never execute contributed commands,
fetch contributed URLs, persist instruction text, or mutate the source topology.
The control variable must be removed from every defaults, kind, group, and node
declaration in the generated deploy topology.

Keep `PLUGIN_SCHEMA`, dynamic help, and `USAGE.md` aligned when changing the
environment key, lifecycle, precedence, or contribution model. The schema's
one-line explanations stay concise; operator details belong in `USAGE.md`.

## Validation

```bash
.venv/bin/ruff check plugins/engulf-clab-instructions/src
.venv/bin/mypy --strict plugins/engulf-clab-instructions/src
.venv/bin/python -m compileall -q plugins/engulf-clab-instructions/src
make build-engulf-clab-instructions
```
