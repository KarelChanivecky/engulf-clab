# Contributing

The package separates pure topology/allocation logic (`allocation.py`), host
observation (`host.py`), versioned state (`registry.py`), and Engulf lifecycle
integration (`plugin.py`). The source topology is immutable; the plugin runs at
priority `-90` after current node-producing mutators and before the writer.

`analyze_call()` validates only normalized options. `prepare_call()` reads the
final materialized node set, holds the allocator lease, inspects Docker and all
host route tables, runs bounded probes, records a pending claim, and adds
deferred topology edits. State transactions must never surround subprocesses.

Preparation has two rollback paths. The inner `except BaseException` removes
this callback's pending claim while its lease is current. `prepare_failed()`
reacquires the lease after callback deactivation. Both restore inactive history
evicted by this attempt and leave older active claims untouched.

After a wrapped process starts, a failed or interrupted deployment is uncertain
and remains reserved. A successful deployment promotes the pending claim and
retires the lab's prior allocation. Successful destroy marks claims inactive;
`--keep-mgmt-net` deliberately retains them.

Validate narrowly with:

```bash
.venv/bin/python -m pytest -q plugins/engulf-clab-sticky-ip/tests
.venv/bin/python -m compileall -q plugins/engulf-clab-sticky-ip/src
make build-engulf-clab-sticky-ip
make check-skill
```
