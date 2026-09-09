# engulf-docker-image-core

Resolves Docker image requirements recursively through independent providers,
discovers literal `FROM` and external `COPY --from` dependencies, and builds the selected DAG dependency
first while relying on Docker's cache.

See [USAGE.md](USAGE.md) and [CONTRIBUTING.md](CONTRIBUTING.md).
