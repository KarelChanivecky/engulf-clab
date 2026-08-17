# engulf-clab-containers

The `engulf_clab.containers` manager consumes declarations from active Engulf
container-collection plugins. A lab selects a packaged recipe with an explicit
node image such as `eclab.containers/host-connector`. The manager injects the
recipe's valid Containerlab node fields and Docker build controls into the
temporary topology; the source topology is unchanged.

## Contents

- [Topology use](#topology-use)
- [Injected and merged fields](#injected-and-merged-fields)
- [Lifecycle and ordering](#lifecycle-and-ordering)
- [Authoring collections](#authoring-collections)
- [Troubleshooting](#troubleshooting)

Install the manager plus one or more collection packages. The maintained core
collection is the usual starting point:

```bash
python -m pip install \
  engulf-clab-containers \
  engulf-clab-containers-core
```

Run `eclab --eclab-containers-help` to list containers supplied by active
collections. The maintained `eclab.containers` collection currently supplies
the host-connector recipe. The list is emitted through Engulf diagnostics.

## Topology use

The image is the only selection syntax. All other node fields remain normal
Containerlab YAML:

```yaml
name: packaged-demo

topology:
  nodes:
    client:
      image: eclab.containers/host-connector
      env:
        ECLAB_CONNECT_HOST: "10.10.10.50;192.0.2.50"
  links: []
```

Both `<namespace>/<name>` and `<namespace>/<name>:latest` select a managed
recipe. No other tag is supported. If a namespace belongs to an active
collection, an unknown name or non-`latest` tag is rejected instead of being
treated as an ordinary registry image.

## Injected and merged fields

For each match, the manager defers these fields through the shared topology
editor:

| Field | Merge behavior |
| --- | --- |
| `image` | Canonicalized to `<namespace>/<name>:latest`. |
| `kind` | Set to the recipe kind, normally `linux`; a conflicting explicit value fails. |
| `image-pull-policy` | Required to be `Never`, because the Dockerfile builder creates the local image. |
| `cap-add` | Existing string entries are preserved and missing required capabilities are appended. |
| `sysctls` | Existing mapping is preserved; a different value for a required key fails. |
| `env` | Lab configuration is preserved; recipe defaults and `ECLAB`-prefixed Dockerfile/context paths are added, and conflicts fail. |

A recipe with `requires_management=True` needs Containerlab's management
`eth0`. An absent/default or explicit `network-mode: bridge` is accepted; an
incompatible network mode fails before preparation. Recipes may reserve `eth0`
for management and treat later interfaces as lab-facing, so follow the selected
container's own README.

The Docker controls use a fixed `ECLAB` prefix, the same across every edition:
`ECLAB_DOCKERFILE` and `ECLAB_DOCKER_CTX`. Collection packages never need to
know this prefix; only the manager injects it.

## Lifecycle and ordering

Collection plugins register immutable recipes during Engulf's before-goal
phase. For deploy, the manager validates the whole active catalog and source
topology during side-effect-free analysis. During preparation it records
deferred mutations after the lab parser and before the Dockerfile builder and
lab writer. Package assets are built only by the builder; this manager does not
invoke Docker itself.

The catalog rejects duplicate names within one collection, duplicate canonical
images, and namespace collisions created by underscore-to-hyphen normalization.
It also verifies that each Dockerfile/context exists and that the Dockerfile is
inside its build context. A collection wheel that omitted package data therefore
fails clearly before a Docker build starts.

The manager has no destroy-time state or cleanup. The generated topology is
removed by `engulf-clab-lab-writer`; Docker images remain in the local daemon's
cache like other Dockerfile-builder outputs.

## Authoring collections

Use `engulf-clab-containers-api` to publish independent typed collections. A
collection owns the namespace derived from its globally unique plugin ID and
must package every build input. Keep recipes generic and push addressing,
credentials, seeds, certificates, routes, and policies into consuming labs.

## Troubleshooting

- If the catalog is empty, confirm that a collection distribution is installed
  and active in the selected launcher or edition.
- If an image is unknown, copy its exact canonical name from
  `--eclab-containers-help`; only `latest` is supported.
- If a field conflicts, remove the incompatible lab override or choose a normal
  unmanaged image. Required recipe values cannot be weakened.
- If assets are missing, rebuild the collection wheel and inspect its contents;
  running from a source checkout can hide package-data omissions.
- If a Docker build fails, continue with the Dockerfile builder's diagnostics;
  successful injection does not prove Docker access or Dockerfile correctness.
