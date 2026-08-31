# Contributing

This package owns the stable version-1 interchange contract. Keep it free of
Containerlab, eclab, YAML, Docker subprocesses, and application-specific
prefixes. Public values are frozen and validate mutable inputs at construction.

Provider selection and Dockerfile parsing belong to `engulf-docker-image-core`.
Application adapters own input parsing and invocation-context registration.
Changes to dataclass fields, requirement parameter semantics, authority ordering,
terminal-rejection or execution-fallback semantics, context IDs, goal identity,
or provider callback behavior require API compatibility review and direct
consumer tests.

`DockerPullRecipe.only_if_missing` is execution policy, not provider discovery.
It defaults to false for compatibility; the core's built-in fallback sets it to
true when local Docker state should satisfy an otherwise unclaimed requirement.

Validate with `python -m pytest plugins/engulf-docker-image-api/tests` and run
the core, Dockerfile adapter, and container-manager suites after contract
changes.
