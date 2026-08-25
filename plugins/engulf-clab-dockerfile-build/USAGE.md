# engulf-clab-dockerfile-build

Builds node images before `eclab deploy`. The host needs a reachable `docker`
command and daemon access. Help, non-deploy commands, and topologies without a
Dockerfile declaration do not build images.

Install with `python -m pip install engulf-clab-dockerfile-build`; it is also
included in `engulf-clab-all-plugins`.

## Configuration

Declare the build on one node; other nodes may reuse its image tag:

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

The `ECLAB` prefix is fixed across editions. The node `image` must be a literal
Docker tag; Containerlab variable forms such as `$TAG`, `${TAG}`, and
`${TAG:-dev}` are rejected because the plugin builds the image before
Containerlab expands topology variables.

Extra arguments are shell-tokenized but executed directly without a shell. They
may not set `--file` or `--tag` in short, long, attached, or equals form; the
declared Dockerfile and node image remain authoritative. Treat build and extra
arguments as non-secret lab input. Use Docker-supported secret mechanisms
configured outside shareable YAML for sensitive material.

`--eclab-docker-build-jobs COUNT` sets parallelism and defaults to `2`.
`ECLAB_DOCKER_BUILD_JOBS` is the persistent default; the CLI option wins. Use
`1` to serialize resource-heavy builds.

## Build behavior

Each deploy invokes `docker build` and relies on Docker's layer cache. Distinct
image tags may build concurrently. Definitions sharing a tag must have the same
Dockerfile, context, build arguments, and extra arguments; identical
definitions coalesce, while conflicts fail. Concurrent eclab calls cannot build
the same tag at once.

Validation requires node `env` to be a YAML mapping, paired existing
file/directory paths, a nonempty literal tag, string build-argument values, and
valid extra-argument quoting. Earlier
topology injectors may contribute packaged build recipes. All requested builds
finish so failures can be reported together, and any failed build prevents
deploy.

Destroy removes neither images nor build state. Use lab-specific or immutable
tags when unrelated labs must not overwrite the same Docker identity.

## Troubleshooting

- Run the selected launcher's `--help` and confirm the displayed prefix and the
  `engulf_clab.dockerfile_build` block appear.
- Resolve paths from the topology directory and inspect `.dockerignore` when
  files are absent from the context.
- Use `--eclab-docker-build-jobs 1` to simplify output or reduce resource use.
- Reproduce the reported `docker build` arguments without adding plugin-owned
  file/tag overrides.
- Make duplicate-tag declarations identical or assign distinct tags. Enable
  targeted plugin diagnostics when the reported cause is unclear.

## Runtime schema discovery

The plugin records its node and runtime variables and snapshots this packaged
`USAGE.md` during `before_goal`. The terminal generator exposes those controls
only when this distribution is active.
