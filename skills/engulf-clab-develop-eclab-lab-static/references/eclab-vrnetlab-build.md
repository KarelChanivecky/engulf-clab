# engulf-clab-vrnetlab-build

Builds configured vrnetlab images before `eclab deploy`. Docker, `make`, QEMU,
and the selected vrnetlab builder's prerequisites must be available.

Install with `python -m pip install engulf-clab-vrnetlab-build`, or through
`engulf-clab-all-plugins`; its vrnetlab checkout dependency is installed
automatically.

## Node and source configuration

```yaml
name: my-lab
topology:
  nodes:
    router:
      kind: vendor_router
      image: vrnetlab/my-lab-router:1.0.0
      env:
        ECLAB_VRNETLAB_TYPE: vendor/router
```

`ECLAB_VRNETLAB_TYPE` is the required opt-in builder path beneath the prepared
vrnetlab checkout. Supply a qcow2 or supported archive per node or as a
default:

```bash
eclab deploy -t lab.clab.yml \
  --eclab-vrnetlab-image default=/images/router-base.qcow2 \
  --eclab-vrnetlab-image router-2=/images/router-2.qcow2 \
  --eclab-vrnetlab-build-jobs 2
```

The plugin applies only to deploy and only to nodes with a nonempty
`ECLAB_VRNETLAB_TYPE`. Place image selectors after the `deploy` command; they
are plugin-owned deploy options rather than Containerlab root flags. Each exact
node or reserved `default` selector may appear once. A bare path remains a
compatibility spelling of `default=PATH`; prefer the explicit form.

Completion offers `default=` plus opted-in node names, reading the topology
selected by `-t`, `--topo`, or `--topology` and otherwise falling back to the
sole recognized topology file in the current directory. It resolves paths from
the topology directory, emits only the normalized selector form, and suggests
the option without a trailing `=`, producing `--eclab-vrnetlab-image
default=PATH` as two shell words.

`--eclab-vrnetlab-build-jobs` defaults to `2`; its persistent default is
`ECLAB_VRNETLAB_BUILD_JOBS`, and the CLI wins. It must be a positive integer.
Set it to `1` for serial builds, or when builds compete for host memory or disk
bandwidth.

## Source precedence

For each opted-in node:

1. exact CLI node selector;
2. node `env.ECLAB_VRNETLAB_IMG_PATH`;
3. CLI `default` selector;
4. invocation `ECLAB_VRNETLAB_IMG_PATH`;
5. legacy `ECLAB_VM_IMG`, then `ECLAB_VM_SRC`.

A source may be a literal path, `$VARIABLE`, or `${VARIABLE}`. Relative paths
use the topology directory. For `$IMAGE_SOURCE` on node `router-1` in lab
`my-lab`, variables are tried in this order:

```text
MY_LAB_ROUTER_1_IMAGE_SOURCE
MY_LAB_IMAGE_SOURCE
IMAGE_SOURCE
```

Names are uppercased and non-alphanumeric runs become underscores. Supported
inputs are `.qcow2`, `.zip`, `.tar`, `.tar.gz`, and `.tgz`; an archive must
contain exactly one qcow2. With no configured source, an existing local Docker
image under the requested tag is accepted; otherwise deploy fails.

## Validation and build lifecycle

The ensure plugin supplies a vrnetlab checkout. Analysis is side-effect free
and validates topology shape, node fields, requested image and source syntax,
positive job count, and builder-relative type safety before preparation begins.
The type must be a safe relative `vendor/type` directory containing a
`Makefile`; absolute paths, traversal, or missing builders fail. Source archives are not extracted
wholesale: only the single qcow2 member is streamed, retaining its basename for
builder tag logic.

A fingerprint covers the requested image, source checksum and basename,
checkout identity, and builder type. A matching record plus an existing
requested Docker tag allows reuse. Otherwise the plugin safely places the input
for Make, moves aside and restores pre-existing builder qcow2 files, removes
stale `docker/*.qcow2*` artifacts around the build, and records the fingerprint
after the requested tag exists. It never modifies or updates the checkout
outside those temporary build inputs.

Builders in different directories may run concurrently up to the configured job
limit. Builds sharing a builder directory remain serialized because that directory is temporarily
modified. Docker-tag and builder leases also coordinate separate eclab calls.

After Make succeeds, the native builder tag remains and the exact topology
image tag is added when different. Use a requested tag unique to the lab:
Docker tags and fingerprints are host-global, so sharing a mutable requested
tag couples otherwise independent labs. Destroy removes neither images nor
fingerprint history.

## Security and MCP

VM images may be licensed or sensitive. Prefer variable indirection over host
paths in shared YAML. Under MCP, every referenced image-source variable is
profile-owned because the service can read its resolved path. Lifecycle callers
cannot override these inputs or pass arbitrary image selectors; configure them
through the selected root-owned profile or topology contract.

A frozen archive handles sources according to its normal or offline policy and
never packages generated appliance images in strict offline mode; an entitled
recipient supplies the VM input and rebuilds locally.

## Troubleshooting

- Confirm ensure-vrnetlab and vrnetlab-build appear in the same launcher's help
  and plugin list.
- Confirm exact selectors name opted-in nodes and are not repeated; use
  `default=PATH` for fallback.
- Verify `<checkout>/<vendor>/<type>/Makefile` and that an archive contains one
  qcow2.
- Trace node, lab, then global variable selection; literal relative paths start
  at the topology directory.
- Use one build job to isolate resource pressure. Same-directory builders are
  serialized regardless.
- Unexpected rebuilds mean the requested tag is absent or a source, checkout,
  type, tag, or fingerprint input changed.
- If a stale `docker/*.qcow2*` artifact cannot be removed, fix ownership or
  permissions on the checkout; the build fails rather than working around it.
- Preserve diagnostics after failure; original builder inputs should be restored
  and the Docker context left clean.
