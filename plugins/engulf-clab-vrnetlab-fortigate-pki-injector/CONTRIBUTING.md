# Contributing

`plugin.py` owns the complete adapter. Keep `analyze_call()` side-effect free and
perform translation only in deploy `prepare_call()`. Consume immutable values
from `PKI_NODE_PROJECTIONS_CONTEXT`; never import the PKI implementation, inspect
its state directories, read `inventory.json`, or parse certificate content.

Validate the current topology node, effective environment collisions, exact
read-only bind, lexical host/container correspondence, and regular-file
availability before recording any mutation. Preserve projection order and
deduplicate by fingerprint. Omit empty categories. This package owns no host
state and therefore needs no unwind callback.

Declare ordering in `pyproject.toml`: parser before, PKI before, writer after,
and schema compiler after. Keep runtime help and `USAGE.md` synchronized with the
five launcher-owned names. Run:

```text
python -m compileall -q src
python -m pytest -q tests
python -m build --no-isolation
make check-skill
```
