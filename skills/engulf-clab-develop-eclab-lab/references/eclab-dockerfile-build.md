# engulf-clab-dockerfile-build

Builds Docker images before `eclab deploy`. Install it with
`python -m pip install engulf-clab-dockerfile-build`; it is also included in
`engulf-clab-all-plugins`.

The host needs a reachable `docker` command and permission to use its daemon.
The plugin activates only for deploy and only when at least one node declares a
nonempty Dockerfile field for the active application prefix. Help and topology
analysis do not build images.

## Contents

- [Use](#use)
- [Node environment fields](#node-environment-fields)
- [Runtime environment](#runtime-environment)
- [Behavior](#behavior)
- [Troubleshooting](#troubleshooting)

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

Use these `env` keys. The `ECLAB` prefix is fixed and the same across every
edition.

| Field | Required | Meaning |
| --- | --- | --- |
| `ECLAB_DOCKERFILE` | With context | Dockerfile path. |
| `ECLAB_DOCKER_CTX` | With Dockerfile | Docker build-context directory. |
| `ECLAB_DOCKER_VAR_<name>` | No | Adds `--build-arg <name>=<value>`. |
| `ECLAB_DOCKER_ARGS` | No | Additional shell-quoted `docker build` arguments. |

The plugin owns `--file` and `--tag`; do not put either in
`*_DOCKER_ARGS`. Docker is required on the host.

`*_DOCKER_ARGS` is parsed with shell-style quoting into an argument vector and
is passed directly to `docker build` without a shell. Short/long forms of
`--file` and `--tag`, including attached values, are rejected because the plugin
must keep the declared Dockerfile and node image authoritative. Treat all extra
arguments and build arguments as build inputs; do not place secrets in topology
YAML. Use Docker-supported secret mechanisms provisioned outside a shareable lab
when sensitive build material is unavoidable.

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

During analysis the plugin requires node `env` to be a mapping, a paired
Dockerfile/context declaration, a nonempty node image tag, an existing
Dockerfile file, an existing context directory, string build-argument values,
and valid extra-argument quoting. Relative paths resolve from the selected
topology's directory, not the invoking shell's current directory. Absolute paths
are allowed but make a lab less portable and may cross the privileged MCP
boundary; prefer lab-relative package inputs.

During preparation it materializes the shared topology session so earlier
injectors—especially packaged-container collections—can contribute build
recipes. It acquires one lease set for every image tag before starting workers,
preventing concurrent eclab calls from building the same tag simultaneously.
All requested builds are allowed to finish so multiple failures can be reported
together. A failed build prevents Containerlab deployment.

The plugin does not remove Docker images after destroy and does not maintain a
separate build fingerprint. Every deploy invokes Docker build, relying on
Docker's normal layer cache. Use an immutable or namespaced tag when unrelated
labs must not overwrite one another's local image.

## Troubleshooting

- Run the selected launcher's `--help` and confirm the displayed prefix and
  `engulf_clab.dockerfile_build` block.
- Confirm paths from the topology directory and inspect `.dockerignore` when
  expected files are absent from the context.
- Set `ECLAB_DOCKER_BUILD_JOBS=1` to make resource-heavy or
  ordering-sensitive build output easier to read.
- Enable targeted plugin diagnostics and reproduce the equivalent `docker build`
  argument vector without adding plugin-owned `--file`/`--tag` overrides.
- If two nodes conflict, make their complete build declarations identical or
  give them distinct image tags.
