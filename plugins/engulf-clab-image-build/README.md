# engulf-clab-image-build

Thin eclab adapter that turns final Containerlab node images and plugin graph
fragments into the neutral Docker image graph, resolves providers recursively,
and runs the shared dependency-first scheduler.

It also restores and persists sanitized Docker image provenance in workspace
state so later calls, including freeze, can inspect the last deploy's providers.

See [USAGE.md](USAGE.md) and [CONTRIBUTING.md](CONTRIBUTING.md).
