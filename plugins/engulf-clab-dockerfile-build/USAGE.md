# engulf-clab-dockerfile-build

Contributes node-owned Dockerfile recipes to the shared image graph before
`eclab deploy` and single-source `eclab redeploy`. The image dispatcher resolves recursive `FROM` dependencies
through installed providers and runs Docker. Help, other commands, and
topologies without a Dockerfile declaration do not add recipes.

Install with `python -m pip install engulf-clab-dockerfile-build`; it is also
included in `engulf-clab-all-plugins`. The beta release requires the Engulf 1.0
plugin APIs used for packaging-declared dependency ordering.

## Configuration

Declare each build as a node. Mark dependency-only builds so they contribute a
complete recipe without becoming Containerlab runtime nodes:

```yaml
topology:
  nodes:
    base-build:
      image: example/base:dev
      env:
        ECLAB_DOCKERFILE: base/Dockerfile
        ECLAB_DOCKER_CTX: base
        ECLAB_DOCKER_VAR_VERSION: "1.2.3"
        ECLAB_DOCKER_ARGS: "--label 'team=netops'"
        ECLAB_DOCKER_BASE_NODE: "true"
    api:
      image: example/api:dev
      env:
        ECLAB_DOCKERFILE: api/Dockerfile
        ECLAB_DOCKER_CTX: api
```

With `FROM example/base:dev` in `api/Dockerfile`, both recipes retain their own
Dockerfile, context, build arguments, and extra flags. `base-build` remains an
image-graph root but is deleted from the temporary topology before Containerlab
runs. The source YAML is unchanged.

Paths are absolute or relative to the topology file's directory, not the
invoking shell's current directory. The recommended layout gives every node a
directory and places its Dockerfile and context there. Absolute paths resolve on
the launcher or service host and may cross a privileged MCP profile's filesystem
boundary; prefer topology-relative packaged inputs.

| Node `env` field | Meaning |
| --- | --- |
| `ECLAB_DOCKERFILE` | Dockerfile path; must be paired with the context. |
| `ECLAB_DOCKER_CTX` | Build-context directory; must be paired with the Dockerfile. |
| `ECLAB_DOCKER_VAR_<name>` | Adds `--build-arg <name>=<value>`. |
| `ECLAB_DOCKER_ARGS` | Extra shell-quoted `docker build` arguments. |
| `ECLAB_DOCKER_BASE_NODE` | Boolean string; build the image but omit this node from the derived deploy topology. |

The `ECLAB` prefix is fixed across editions. The node `image` must resolve to a
literal Docker tag during the shared parser's eager Containerlab-compatible
environment expansion. Forms such as `$TAG`, `${TAG}`, and `${TAG:-dev}` are
supported when they resolve; any expression still present afterward is rejected.

Because Containerlab node environment values are strings, quote the marker as
`"true"`. The accepted boolean spellings are `true`, `false`, `1`, `0`, `yes`,
`no`, `on`, and `off`. A true marker requires the same `image`, Dockerfile, and
context fields as an ordinary Dockerfile node.

Extra arguments are shell-tokenized but executed directly without a shell. They
may not set `--file` or `--tag` in short, long, attached, or equals form; the
declared Dockerfile and node image remain authoritative. Treat build and extra
arguments as non-secret lab input. Use Docker-supported secret mechanisms
configured outside shareable YAML for sensitive material.

`--eclab-image-build-jobs COUNT` sets dispatcher parallelism and defaults to
`2`; `ECLAB_IMAGE_BUILD_JOBS` is its persistent default. The former
`--eclab-docker-build-jobs` and `ECLAB_DOCKER_BUILD_JOBS` spellings remain
compatible. Use `1` to serialize resource-heavy builds.

## Build behavior

Each deploy contributes the same immutable recipe, and the dispatcher invokes
`docker build` for every selected provision while relying on Docker's layer
cache. Literal external `FROM` images enter the same provider chain recursively
and provision before their consumers. Dynamic bases must resolve from declared
global build arguments; otherwise provisioning fails before Docker runs.

Every marked base node is an explicit graph root, so it builds even when no
runtime node references it. Its deletion happens only in the derived deploy
topology, after recipe extraction and before image resolution and writer
serialization. Build-only images and Docker cache state remain after destroy.
The preparation step changes only invocation-scoped topology and image-graph
context; if a later plugin cannot prepare, Engulf discards that invocation and
there is no Docker resource from this adapter to roll back.

`ECLAB_DOCKER_ARGS` must not enable `--pull`. Base-image selection and fallback
belong to the image graph, including configured mirror pull providers.
Independent tags may build concurrently. Definitions sharing a tag must have
the same Dockerfile, context, build arguments, and extra arguments; identical
definitions coalesce, while conflicts fail. Concurrent calls cannot build the
same tag at once.

Validation requires node `env` to be a YAML mapping, paired existing
file/directory paths, a nonempty literal tag, string build-argument values, and
valid extra-argument quoting. Other plugins contribute providers or graph
fragments through the neutral contract without importing this plugin. All
started builds finish so failures can be reported together, and any failed
build prevents deploy.

Destroy removes neither images nor build state. Use lab-specific or immutable
tags when unrelated labs must not overwrite the same Docker identity.

## Troubleshooting

- Run the selected launcher's `--help` and confirm the displayed prefix and the
  `engulf_clab.dockerfile_build` block appear.
- Resolve paths from the topology directory and inspect `.dockerignore` when
  files are absent from the context.
- Use `--eclab-image-build-jobs 1` to simplify output or reduce resource use.
- Reproduce the reported `docker build` arguments without adding plugin-owned
  file/tag overrides.
- Make duplicate-tag declarations identical or assign distinct tags. Enable
  targeted plugin diagnostics when the reported cause is unclear.
- If a base node appears in Containerlab output, verify the marker is a
  quoted true boolean string and that `engulf_clab.dockerfile_build` runs before
  the image dispatcher and topology writer.

## Runtime schema discovery

The plugin records its Dockerfile node variables and snapshots this packaged
`USAGE.md` during `before_goal`. Dispatcher controls and node-local image
parameters are declared by `engulf_clab.image_build`.
