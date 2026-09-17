# Contributing to engulf-clab-lab-registry-api

Keep this package independent of the registry implementation and individual
consumers. Public records are immutable, validate their identity and path
invariants, and contain only generic lab inventory—not resource measurements or
feature-specific state. `Workspace` owns absolute-path validation and
canonicalization at the API boundary; derive record identity from it rather than
comparing raw paths. Keep the context names and plugin ID stable.

The registry protocol carries a persistence flag and a load-time revision so a
consumer can fence a decision against a concurrent writer, and the commit
outcome is the shared vocabulary for "did my intent reach durable storage". Both
belong here rather than in one implementation: `engulf-clab-reclaim` must be
able to run its delete-after-commit ordering against any registry that honors
the contract. Adding a protocol member is a breaking change for providers, so
bump the minor version, update `USAGE.md`, and update direct consumers together.

Add API fields or methods only when multiple consumers need them. Evolve
incompatible contracts with a new major version and update direct consumers.

Validate the contract and direct consumers with:

```bash
PYTHONPATH=plugins/engulf-clab-lab-registry-api/src \
  .venv/bin/python -m pytest -q plugins/engulf-clab-lab-registry-api/tests
PYTHONPATH=plugins/engulf-clab-lab-registry-api/src:plugins/engulf-clab-consumption/src \
  .venv/bin/python -m pytest -q plugins/engulf-clab-consumption/tests
```
