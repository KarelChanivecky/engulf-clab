# Contributing to engulf-clab-lab-registry-api

Keep this package independent of the registry implementation and individual
consumers. Public records are immutable, validate their identity and path
invariants, and contain only generic lab inventory—not resource measurements or
feature-specific state. Keep the context name and plugin ID stable.

Add API fields or methods only when multiple consumers need them. Evolve
incompatible contracts with a new major version and update direct consumers.

Validate the contract and direct consumers with:

```bash
PYTHONPATH=plugins/engulf-clab-lab-registry-api/src \
  .venv/bin/python -m pytest -q plugins/engulf-clab-lab-registry-api/tests
PYTHONPATH=plugins/engulf-clab-lab-registry-api/src:plugins/engulf-clab-consumption/src \
  .venv/bin/python -m pytest -q plugins/engulf-clab-consumption/tests
```
