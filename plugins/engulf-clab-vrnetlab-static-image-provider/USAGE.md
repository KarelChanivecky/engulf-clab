# engulf-clab-vrnetlab-static-image-provider

This package is the local-file source provider for vrnetlab image construction.
It resolves one source path for each opted-in node and publishes those paths to
the shared `engulf-clab-vrnetlab-build` through
`engulf-clab-vrnetlab-build-api`. The builder stages qcow2 inputs, runs the
selected vrnetlab Makefile, and registers the resulting image recipe. Build
prerequisites include Docker, `make`, QEMU tools, and the selected builder's
requirements.

The source provider ID is `engulf_clab.vrnetlab_static_image_provider`; the
shared builder ID is `engulf_clab.vrnetlab_build`. Installing this package
installs the backend and API automatically. Other providers can be installed
alongside it and contribute paths through the same API. Runtime help and the
plugin list show which providers are installed for the selected edition.

Install with `python -m pip install engulf-clab-vrnetlab-static-image-provider`,
or through `engulf-clab-all-plugins`; its vrnetlab checkout dependency is
installed automatically.

## Node and source configuration

Containerlab YAML remains the base language. Keep the topology valid against
the upstream [Containerlab topology schema](https://github.com/srl-labs/containerlab/blob/main/schemas/clab.schema.json);
this provider adds its fields as conventions layered onto that syntax.

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

The provider applies only to deploy and single-source redeploy, and only to nodes
with a nonempty `ECLAB_VRNETLAB_TYPE`. The type, image, and image-source
environment values inherit through `defaults < kind < group < node`; the node
view's winning values are used. Place image selectors after the command;
they are plugin-owned deployment options rather than Containerlab root flags. Each exact
node or reserved `default` selector may appear once. The node-specific selector
is the explicit node override: it replaces that configured node's YAML source
and the environment fallback. For example,
`--eclab-vrnetlab-image router-2=/images/router-2.qcow2` overrides only
`router-2`. `default=PATH` overrides every node YAML source that does not have
its own selector and also supplies the fallback. A bare path remains a
compatibility spelling of `default=PATH`; prefer the explicit form.

Every node that receives the `default=PATH` source must have the same
`ECLAB_VRNETLAB_TYPE`. For example, `fortinet/fortigate` and
`fortinet/fortiproxy` nodes cannot share one default source because the
FortiGate image is not a FortiProxy image. Use node-specific selectors or YAML
sources when a topology contains multiple builder types. The shared builder
also enforces this rule for providers that publish a default source through the
API.

Completion offers `default=` plus opted-in node names, reading the topology
selected by `-t`, `--topo`, or `--topology` and otherwise falling back to the
sole recognized topology file in the current directory. It resolves paths from
the topology directory, emits only the normalized selector form, and suggests
the option without a trailing `=`. When the cursor is directly after the
option, completion inserts the valid two-word form
`--eclab-vrnetlab-image default=`; after the separating space it offers
`default=` and opted-in node selectors. The option never uses an
`--eclab-vrnetlab-image=...` spelling.

`--eclab-vrnetlab-build-jobs` defaults to `2`; its persistent default is
`ECLAB_VRNETLAB_BUILD_JOBS`, and the CLI wins. It must be a positive integer.
Set it to `1` for serial builds, or when builds compete for host memory or disk
bandwidth.

## Source precedence

For each opted-in node:

1. exact CLI node selector;
2. CLI `default` selector;
3. node `env.ECLAB_VRNETLAB_IMG_PATH`;
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
contain exactly one qcow2. With no configured source, the node still opts into
the provider: if a local Docker image under the requested tag exists it is
reused, otherwise deploy fails with a resolution error naming the missing
source.

The provider resolves each winning value before publishing it. When every
opted-in node has the same path, it writes the API's `default` entry; otherwise
it writes node-specific entries. The API rejects a second provider write for
the same node or `default` key.

## Validation and build lifecycle

Freeze discovers this package's image inputs through
`engulf_clab.freeze.images.v1` without preparing or running builds. Default
freeze retains a rebuild only when its VM input is included in the lab;
otherwise it exports the existing container image and removes build controls
from the portable topology. It does not copy external QCOW files automatically.
Offline freeze captures the output because builders may require network access.
Lean freeze substitutes a recipient VM-input variable, omits referenced
lab-local VM inputs, and retains the builder selection. Missing or unset inputs
are permitted during freeze discovery; normal deploy validation is unchanged.

The ensure plugin supplies a vrnetlab checkout. Analysis is side-effect free
and validates topology shape, node fields, requested image and source syntax,
positive job count, and builder-relative type safety before preparation begins.
The type must be a safe relative `vendor/type` directory containing a
`Makefile`; absolute paths, traversal, or missing builders fail. Source archives
are not extracted wholesale: the shared builder streams only the single qcow2
member, retaining its basename for builder tag logic.

During preparation, this provider resolves and publishes source paths and the
validated job limit. The single shared builder runs next, pairs those paths
with opted-in node images and builder types, and constructs missing images. It
also registers one `VrnetlabBuildRecipe` adapter with the image-build graph so
any tag still missing at graph resolution can be built from the same request.
The builder serializes work sharing a builder directory and restores prior
Docker tags and builder qcow2 files after builds.

A fingerprint covers the requested image, source checksum and basename,
checkout identity, and builder type. A matching record plus an existing
requested Docker tag allows reuse. Otherwise the builder safely stages the
input for Make, moves aside and restores pre-existing builder qcow2 files,
removes stale `docker/*.qcow2*` artifacts around the build, and records the
fingerprint after the requested tag exists. It never modifies or updates the
checkout outside those temporary build inputs.

Builders in different directories may run concurrently up to the configured job
limit. Builds sharing a builder directory remain serialized because that
directory is temporarily modified. Docker-tag and builder leases coordinate
separate eclab calls, and the image graph holds a `vrnetlab-builder:` lease per
involved builder while provisioning.

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

- Confirm ensure-vrnetlab, vrnetlab-static-image-provider, and vrnetlab-build
  are active in the selected launcher. The backend has no source controls of
  its own.
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
