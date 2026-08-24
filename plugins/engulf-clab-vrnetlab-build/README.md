# engulf-clab-vrnetlab-build

Builds configured vrnetlab node images before `eclab deploy`. Install with
`python -m pip install engulf-clab-vrnetlab-build`; its vrnetlab checkout dependency
is installed automatically. Docker, `make`, and the selected vrnetlab builder
must be available.

## Contents

- [Node configuration](#node-configuration)
- [Source selection](#source-selection)
- [Build behavior](#build-behavior)
- [Activation and validation](#activation-and-validation)
- [Fingerprints, tags, and cleanup](#fingerprints-tags-and-cleanup)
- [Security and MCP](#security-and-mcp)
- [Troubleshooting](#troubleshooting)

## Node configuration

```yaml
name: my-lab

topology:
  nodes:
    router:
      kind: vendor_router
      image: vrnetlab/vr-router:1.0.0
      env:
        ECLAB_VRNETLAB_TYPE: vendor/router
```

| Node `env` field | Meaning |
| --- | --- |
| `ECLAB_VRNETLAB_TYPE` | Required opt-in builder path beneath the vrnetlab checkout, for example `vendor/router`. |

Set the optional qcow2 or supported archive source on the eclab invocation:

```bash
eclab deploy -t lab.clab.yml \
  --eclab-vrnetlab-image default=/images/router.qcow2 \
  --eclab-vrnetlab-build-jobs 2
```

The image option is repeatable. Its selector is either an exact opted-in
topology node name or the reserved `default` fallback:

```bash
eclab deploy -t lab.clab.yml \
  --eclab-vrnetlab-image default=/images/router-base.qcow2 \
  --eclab-vrnetlab-image router-2=/images/router-2.qcow2
```

Shell completion reads the topology selected by `-t`, `--topo`, or `--topology`,
falling back to the sole recognized topology file in the current directory. It
offers `default=` plus nodes that declare `ECLAB_VRNETLAB_TYPE`, and completes the
path after `=` relative to the topology directory. Each selector may appear once.
A bare path remains accepted as a compatibility spelling of `default=PATH`, but
completion emits only the normalized selector form. The option itself is suggested
without a trailing `=`, producing `--eclab-vrnetlab-image default=PATH` as two shell
words.
Place image selectors after the `deploy` command; they are plugin-owned deploy
options rather than Containerlab root flags.

`--eclab-vrnetlab-build-jobs` controls concurrent image builds and defaults to
`2`. Set it to `1` for serial builds or when builds compete for host memory or
disk bandwidth.

The node `image` may differ from the native tag emitted by the builder. After a
successful build, the plugin retains the native tag and adds the requested node
image tag. Use a requested image value unique to the lab, such as a tag that
includes the lab name. Do not reuse that mutable requested tag across
independently launched labs. Docker tags and build-fingerprint state are shared
across workspaces, so lab-unique values avoid cross-lab tag contention and allow
multiple labs to launch concurrently.

`ECLAB_VRNETLAB_IMG_PATH` remains the persistent image fallback.
`ECLAB_VRNETLAB_BUILD_JOBS` is the persistent concurrency default and its CLI
option wins. `ECLAB_VM_IMG` and `ECLAB_VM_SRC` remain legacy image-source
aliases.

## Source selection

The path portion of `--eclab-vrnetlab-image NODE=PATH` may be a literal path,
`$VARIABLE`, or `${VARIABLE}`. A node `env.ECLAB_VRNETLAB_IMG_PATH` value is
also accepted. Source precedence for each opted-in node is:

1. its exact CLI node selector;
2. its topology `env.ECLAB_VRNETLAB_IMG_PATH` value;
3. the CLI `default` selector;
4. the `ECLAB_VRNETLAB_IMG_PATH` environment fallback;
5. deprecated `ECLAB_VM_IMG`, then `ECLAB_VM_SRC` aliases.

An exact CLI selector must name a topology node that declares
`ECLAB_VRNETLAB_TYPE`. `default` is a reserved pseudo-node and supplies only
the fallback for nodes without a more specific source.
Relative paths resolve from the topology directory. For `$IMAGE_SOURCE` on node
`router-1` in lab `my-lab`, the invocation environment is checked in this order:

```text
MY_LAB_ROUTER_1_IMAGE_SOURCE
MY_LAB_IMAGE_SOURCE
IMAGE_SOURCE
```

Lab, node, and variable components are uppercased and non-alphanumeric runs
become underscores. If the node omits the field, the invocation environment may
set the application-prefixed image-path variable directly.

Supported sources are `.qcow2`, `.zip`, `.tar`, `.tar.gz`, and `.tgz`; an archive
must contain exactly one qcow2. If no source is configured, an existing local
Docker image with the requested tag is accepted; otherwise deployment fails.

## Build behavior

The builder directory must contain a `Makefile`. Existing qcow2 files are moved
aside and restored, and stale `docker/*.qcow2*` artifacts are removed around
the build. Build fingerprints live in user-scoped Engulf state, keyed by image,
source checksum/name, checkout fingerprint, and builder type. Leases serialize
access to both the Docker tag and builder directory. Builds using different
builder directories can run concurrently up to the configured job limit;
builds using the same `vendor/type` builder remain serialized because that
directory is modified temporarily.

## Activation and validation

The plugin applies only to deploy and only to nodes with a nonempty
`ECLAB_VRNETLAB_TYPE`. Analysis is side-effect free and validates topology
shape, node fields, requested image/source syntax, positive job count, and
builder-relative type safety before preparation begins.

The hard ensure-vrnetlab dependency must publish context
`engulf_clab.vrnetlab.path`. The selected type is a relative `vendor/type` path
under that checkout; absolute paths, traversal, missing directories, or builders
without a `Makefile` fail. The ensure plugin also requires Docker and QEMU
commands. This builder requires `docker` and `make`; the selected Makefile may
have additional vendor-specific prerequisites.

Source archive extraction is intentionally narrow. The plugin searches for
exactly one qcow2 member and streams only that member to a temporary directory;
it never extracts arbitrary archive paths. The original qcow2 basename is
preserved because vrnetlab Makefiles often derive the native image tag from it.

## Fingerprints, tags, and cleanup

Before building, the plugin calculates a fingerprint from the requested image,
source checksum/basename, prepared checkout fingerprint, and builder type. A
matching fingerprint plus existing requested Docker tag allows reuse. Fingerprint
records live in user-scoped Engulf state because tags are shared across
workspaces.

The selected builder directory is mutable build input. Before invoking Make, the
plugin moves aside pre-existing qcow2 files and removes stale Docker-context
qcow2 artifacts. `finally` cleanup removes temporary inputs/artifacts and
restores original builder files even after failure. It never modifies or updates
the checkout outside those temporary build inputs.

After Make succeeds, the plugin discovers the native image tag created by the
builder and adds the exact topology-requested tag when different. It retains the
native tag. It records the fingerprint only after the requested image exists.
Destroy does not remove built images or fingerprint history.

## Security and MCP

VM images may be licensed or sensitive. Keep literal host paths out of shared
topologies; prefer a `$VARIABLE` indirection and configure its resolved value in
the local environment. A frozen archive handles sources according to its normal
or offline policy and never packages generated appliance images in strict
offline mode.

The MCP service treats every variable referenced by a node image-source field as
profile-owned because the root daemon can read that path. Configure the selected
candidate variable in the root-owned profile; callers cannot provide it as an
override. MCP lifecycle jobs use a fixed argument vector and do not accept image
selectors from callers; configure their sources through the selected profile or
the topology contract.

## Troubleshooting

- Confirm ensure-vrnetlab and vrnetlab-build appear in the same launcher's help
  and plugin list.
- Confirm each exact CLI selector matches an opted-in topology node and that no
  selector is repeated; use `default=PATH` for the fallback.
- Confirm `<checkout>/<vendor>/<type>/Makefile` exists and the source format
  contains exactly one qcow2.
- Trace variable selection in node -> lab -> global order and remember that
  relative literal paths use the topology directory.
- Use `--eclab-vrnetlab-build-jobs 1` to isolate resource pressure or simplify
  output; builders sharing one directory are serialized regardless.
- If an existing Docker tag is unexpectedly rebuilt, compare source checksum,
  checkout revision, builder type, requested tag, and fingerprint state.
- Preserve the builder directory and diagnostics after failure; the plugin
  should restore original qcow2 inputs and remove only its temporary artifacts.

## Runtime schema discovery

The plugin records opt-in, image-source, compatibility-alias, and concurrency
controls and snapshots this packaged README before the runtime schema generator
runs last.
