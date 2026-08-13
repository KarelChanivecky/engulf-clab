# engulf-clab-dockerfile-build

Builds Docker images before `eclab deploy`. Install it with
`python -m pip install engulf-clab-dockerfile-build`; it is also included in
`engulf-clab-all-plugins`.

## Use

Declare a Dockerfile on the node that owns the image. The node's existing
Containerlab `image` value is the resulting Docker tag. Other nodes may reuse
that tag without repeating the Docker definition.

```yaml
topology:
  nodes:
    api:
      image: example/api:dev
      env:
        ECLAB_DOCKERFILE: api/Dockerfile
        ECLAB_DOCKER_CTX: api
        ECLAB_DOCKER_VAR_VERSION: "1.2.3"
        ECLAB_DOCKER_ARGS: "--pull --label 'team=netops'"
    worker:
      image: example/api:dev
```

The recommended layout gives every node a directory and places its Dockerfile
and context there. Paths are relative to the topology file unless absolute.

## Node environment fields

For the official `engulf-clab` application, use these `env` keys. Editions use
their short product name, or full product name if no short name is available:
`acme clab` becomes `ACME_CLAB_*`.

| Field | Required | Meaning |
| --- | --- | --- |
| `ECLAB_DOCKERFILE` | With context | Dockerfile path. |
| `ECLAB_DOCKER_CTX` | With Dockerfile | Docker build-context directory. |
| `ECLAB_DOCKER_VAR_<name>` | No | Adds `--build-arg <name>=<value>`. |
| `ECLAB_DOCKER_ARGS` | No | Additional shell-quoted `docker build` arguments. |

The plugin owns `--file` and `--tag`; do not put either in
`*_DOCKER_ARGS`. Docker is required on the host.

## Runtime environment

`ECLAB_DOCKER_BUILD_JOBS` controls how many distinct image tags may build at
once and defaults to `2`. Editions use their application-specific prefix. Set it
to `1` for serial builds or lower it when Docker builds compete for host memory
or disk bandwidth.

## Behavior

Builds run on each deploy and rely on Docker layer caching. Distinct image tags
build concurrently up to the configured job limit. Multiple definitions for one
image tag must resolve to the same Dockerfile, context, build arguments, and
extra arguments; identical definitions coalesce into one leased build. A node
that only consumes an image tag has no build-related configuration.
