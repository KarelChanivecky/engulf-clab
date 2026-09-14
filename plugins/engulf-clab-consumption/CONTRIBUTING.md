# Contributing to engulf-clab-consumption

The plugin preempts only the `consumption` command in `before_goal`; all other
invocations continue unchanged. Keep Docker and topology collection read-only.
Access inventory only through `engulf-clab-lab-registry-api`. Isolate Docker
subprocess calls in `docker.py`. Tests must use a fake client and must never
depend on a live daemon.

Containerlab labels identify labs and their retained topology paths. Explicit
topology selection is authoritative and shares the lab-parser's discovery and
environment-expansion rules. `--all` merges every Docker-backed lab with the
shared registry and reloads both for every polling sample. Contribute complete
explicit-query and Docker-discovery observations through the API; do not own
deploy tracking or registry persistence here.

Preserve these accounting invariants:

- sum current CPU and RAM for each lab's running containers;
- count allocated directory bytes without following symlinks or duplicating
  hard links;
- deduplicate image IDs within a lab and across the total;
- classify complete image sizes as shared only across distinct lab owners;
- use retained container root-filesystem size only when an image record is gone;
- distinguish Docker-confirmed absence for no-container images from measurement
  failure;
- distinguish running `DEPLOYED`, unique-image-consuming `STOPPED`, and
  zero-unique-image or never-deployed `RECLAIMED` state;
- propagate unavailable measurements as `N/A` instead of zero or a partial sum;
- hold no state transaction or resource lease.

Packaging runs `engulf_clab.lab_registry` before consumption and the
`engulf_clab.schema` compiler after it. Update `PLUGIN_SCHEMA`, dynamic help,
USAGE, tests, the meta-package, root package map, and generated skill together
when behavior changes.

Validate narrowly with:

```bash
.venv/bin/python -m compileall -q plugins/engulf-clab-consumption/src
PYTHONPATH=plugins/engulf-clab-lab-registry-api/src:plugins/engulf-clab-consumption/src \
  .venv/bin/python -m pytest -q plugins/engulf-clab-consumption/tests
make check-skill
```
