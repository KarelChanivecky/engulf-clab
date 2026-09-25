# Contributing to the Fortinet operation guard

This package owns one narrow policy: reject lifecycle operations that current
Fortinet Containerlab nodes cannot perform. It is an executable-wrapper plugin,
not a topology mutator and not a Fortinet runtime manager.

## Contract

The plugin resolves effective `kind:` values from the selected topology. A
FortiGate or FortiProxy node causes `restart` and `deploy --reconfigure` to be
preempted before preparation. Plain `deploy` is allowed only when no matching
Containerlab container for that topology is running. Docker inspection happens
in `prepare_call()` and is read-only.

The topology parser and schema ordering edges are declared in
`pyproject.toml`. Do not add code-level plugin dependencies or use the parser's
mutable session for this policy. The invocation context contains only the
selected immutable target and is discarded after the call.

If Docker inspection fails, fail closed and retain the original inspection error
in the callback diagnostic. Never guess that a lab is stopped when its state
cannot be read.

## Validation

Run the package tests and metadata checks with:

```bash
.venv/bin/python -m pytest -q plugins/engulf-clab-fortinet-operation-guard/tests
.venv/bin/python -m compileall -q plugins/engulf-clab-fortinet-operation-guard/src
make build-engulf-clab-fortinet-operation-guard
```

Mock Docker subprocess calls in unit tests. Do not require a live Docker daemon
or Containerlab installation for this package's tests.
