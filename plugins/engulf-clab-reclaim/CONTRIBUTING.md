# Contributing to engulf-clab-reclaim

The plugin preempts only `reclaim` in `before_goal`. Planning must be
read-only and complete before mutation begins. Preserve lab workspaces and
registry history; the command owns only Containerlab container removal,
anonymous-volume removal, and removal of the explicitly planned image IDs.

Determine image sharing by exact image ID across distinct registry/Docker lab
identities. A single-lab reclamation must never remove an image owned by another
known lab. Plain `--all` must reject the complete plan if any known lab has a
running or stopped container; only then may it remove the shared union. `--all
--stopped` selects stopped-container labs and preserves images owned outside
that subset.
Never pass `--force` to Docker image removal: non-lab containers are outside the
registry's ownership model and Docker must protect them.

Persist complete observations before the first deletion and abort cleanly if
that or the initial Docker storage snapshot fails. Once deletion starts,
continue independent removals, take a final storage snapshot, log every failure
through the callback logger, and return nonzero for partial completion. Compute
saved storage from Docker's aggregate image, container, and local-volume totals;
exclude build cache. Hold the reclamation lease across Docker discovery,
planning, measurement, and mutation so two reclamation commands cannot act on
stale plans. Never add MCP or filesystem-delete behavior.

Packaging runs the lab registry before reclamation and the schema compiler
afterward. Tests use fake Docker and registry boundaries; they must not touch a
live daemon.

Validate narrowly with:

```bash
PYTHONPATH=plugins/engulf-clab-lab-registry-api/src:plugins/engulf-clab-reclaim/src \
  .venv/bin/python -m pytest -q plugins/engulf-clab-reclaim/tests
.venv/bin/python -m compileall -q plugins/engulf-clab-reclaim/src
make check-skill
```
