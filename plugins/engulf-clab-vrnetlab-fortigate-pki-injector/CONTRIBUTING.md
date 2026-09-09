# Contributing

`plugin.py` owns the complete adapter. Keep `analyze_call()` side-effect free and
perform translation only in deploy `prepare_call()`. Consume immutable values
from `PKI_NODE_PROJECTIONS_CONTEXT`; never import the PKI implementation, inspect
its state directories, read `inventory.json`, or parse certificate content.

Validate the current topology node, effective environment collisions, exact
read-only bind, lexical host/container correspondence, and regular-file
availability before recording any mutation. Preserve projection order and
deduplicate by fingerprint. Every CA, remote, local, and CRL launcher entry must
start with a refname field; never emit the ambiguous legacy bare-path or
`key_path:cert_path` forms. Derive stable names from projection identities,
reject within-category name collisions, and omit empty categories. This package
owns no host state and therefore needs no unwind callback.

Build-only nodes may have projections because PKI sees the source topology, but
an image provider removes them from the deployable topology before this adapter
runs. Skip projections whose nodes are absent; malformed values for nodes that
remain are still errors.

Record each generated environment variable at its leaf path. PKI consumes its
controls by replacing the surrounding `env` mapping, so replacing that mapping
again from the injector creates a writer conflict even when the resulting keys
would be disjoint.

The current producer exposes unencrypted CA/local material only. Keep password
files, remote certificates, and CRLs absent until the typed projection API
provides their node-authorized paths; never infer them by parsing staged files.

Declare ordering in `pyproject.toml`: parser before, PKI before, writer after,
and schema compiler after. Keep runtime help and `USAGE.md` synchronized with the
five launcher-owned names. Run:

```text
python -m compileall -q src
python -m pytest -q tests
python -m build --no-isolation
make check-skill
```
