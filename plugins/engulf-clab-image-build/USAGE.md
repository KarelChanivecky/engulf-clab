# engulf-clab-image-build

This plugin is the eclab dispatcher for Docker image requests. It scans the
materialized deploy topology's ordinary node `image` fields, merges graph
fragments contributed by installed adapters, asks every registered provider,
and invokes the application-neutral resolver and scheduler. It does not define
a new Containerlab YAML field.

The compact generated capability schema exposes the essential recursion
directly on the standard node `image` property: each literal image is a graph
root, active providers are queried again for every literal Dockerfile `FROM`
base, and selected recipes build dependency-first. This guide supplies detail;
agents do not need to open it merely to discover that recursive building exists.

Install it directly or through `engulf-clab-all-plugins`. A normal topology
continues to use ordinary literal node images. Providers are ranked by declared
authority, then plugin priority and ID. An unclaimed image receives the built-in
low-authority pull offer, so the dispatcher provisions every root and literal
Dockerfile base instead of delegating that work to Containerlab or `docker
build`. Providers should not probe registries while answering; the selected
pull operation is the availability check.

When a preferred mirror/cache offer fails during execution, resolution runs
again without that exact offer and selects the next eligible provision. A
terminal rejection blocks equal- or lower-authority fallbacks for a namespace,
and an owned build provider may disable execution fallback so its real build
error is not hidden by an unrelated registry pull.

Custom provider parameters also remain valid Containerlab syntax because they
are node environment variables:

```yaml
topology:
  nodes:
    app:
      image: example/app
      env:
        ECLAB_IMAGE_PARAM_RELEASE: "2026.08"
```

`ECLAB_IMAGE_PARAM_*` applies only to the image on that node. It is never copied
to a Dockerfile dependency. Give another image its own topology node when it
needs distinct provider configuration; use `ECLAB_DOCKER_BASE_NODE: "true"`
when that declaration exists only to build an image. Values must be strings.
These are build-time controls visible in the source topology; never put secrets
in them. The `ECLAB` prefix is fixed across editions so the same valid
Containerlab file is portable between compatible launchers.

`--eclab-image-build-jobs COUNT` limits independent concurrent builds and
defaults to `2`. `ECLAB_IMAGE_BUILD_JOBS` is its persistent environment default.
The former `--eclab-docker-build-jobs` spelling remains an alias, and
`ECLAB_DOCKER_BUILD_JOBS` remains a fallback for compatibility.

Every selected provision is executed on every deploy, dependencies first.
Docker's layer and pull caches decide whether work can be reused. Build output
tags and mirror pull sources are leased for the invocation. After successful
provisioning, the derived topology sets every literal root's
`image-pull-policy` to `Never`; the source topology is not changed. Images and
Docker cache state are retained after destroy.

The plugin requires literal node image values and statically resolvable
Dockerfile `FROM` values so it can own the complete provisioning graph. The host
`docker` command and daemon authorization are required for every deploy that has
an image root.

## Troubleshooting

- Run `eclab --help` and confirm `engulf_clab.image_build` is active, then use
  `eclab --engulf-plugin-list` when that diagnostic is installed to verify
  contributors run before it.
- Copy provider-owned image names exactly. An authoritative “unknown image” or
  unsupported-tag rejection means the provider recognized its namespace and
  deliberately refused the request.
- Use `--eclab-image-build-jobs 1` to serialize output while diagnosing a
  dependency failure.
- Inspect each reported Dockerfile `FROM` chain. If a dynamic base cannot be
  expanded, declare the required global build argument so it becomes a literal
  graph requirement.

## Runtime schema discovery

The adapter records the node-local parameter pattern, both runtime environment
spellings, and the current/legacy CLI flag names during `before_goal`. Its
packaged `USAGE.md` is snapshotted only when this distribution is active.
