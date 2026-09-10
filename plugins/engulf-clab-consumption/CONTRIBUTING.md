# Contributing to engulf-clab-consumption

The plugin preempts only the `consumption` command in `before_goal`; all other
invocations continue unchanged. Keep collection read-only and isolate Docker
subprocess calls in `docker.py`. Tests must use a fake client and must never
depend on a live daemon.

Containerlab labels identify labs and their retained topology paths. Explicit
topology selection is authoritative and shares the lab-parser's discovery and
environment-expansion rules. `--all` includes running containers only and is
rediscovered for every polling sample.

Preserve these accounting invariants:

- sum current CPU and RAM for each lab's running containers;
- count allocated directory bytes without following symlinks or duplicating
  hard links;
- deduplicate image IDs within a lab and across the total;
- keep Docker's image-level shared and unique definitions visible;
- propagate unavailable measurements as `N/A` instead of zero or a partial sum;
- do no host mutation and hold no state transaction or resource lease.

The package declares ordering after `engulf_clab.schema` for schema collection.
Update `PLUGIN_SCHEMA`, dynamic help, USAGE, tests, the meta-package, root package
map, and generated skill together when behavior changes.

Validate narrowly with:

```bash
.venv/bin/python -m compileall -q plugins/engulf-clab-consumption/src
PYTHONPATH=plugins/engulf-clab-consumption/src:plugins/engulf-clab-lab-parser/src \
  .venv/bin/python -m pytest -q plugins/engulf-clab-consumption/tests
make check-skill
```
