# Contributing

This package owns the stable version-1 interchange contract. Keep it free of
Containerlab, eclab, YAML, Docker subprocesses, and application-specific
prefixes. Public values are frozen and validate mutable inputs at construction.

Provider selection and Dockerfile parsing belong to `engulf-docker-image-core`.
Application adapters own input parsing and invocation-context registration.
Changes to dataclass fields, requirement parameter semantics, authority ordering,
terminal-rejection or execution-fallback semantics, context IDs, goal identity,
provenance semantics, or provider callback behavior require API compatibility
review and direct consumer tests. `DockerImageProvenanceSnapshot` records only
Docker image provider resolution and has one selected-provider record per
image. Do not add source-provider IDs or vrnetlab source fingerprints here; those
are a separate registry owned by the vrnetlab build API. Keep workspace state
loading and writing in the application adapter, not here.

Keep `DOCKER_IMAGE_PROVENANCE_CONTEXT` optional for consumers by publishing with
`allow_unused=True`. This prevents a successful invocation from warning when no
consumer is installed; it does not bypass declared read/write capabilities.
Direct writers must preserve the same flag. Consumers declare the public
context in `context_reads` and use the packaging dependency edge when they need
the current deploy result.

`DockerPullRecipe.only_if_missing` is execution policy, not provider discovery.
It defaults to false for compatibility; the core's built-in fallback sets it to
true when local Docker state should satisfy an otherwise unclaimed requirement.

Validate with `python -m pytest plugins/engulf-docker-image-api/tests` and run
the core, Dockerfile adapter, and container-manager suites after contract
changes.
