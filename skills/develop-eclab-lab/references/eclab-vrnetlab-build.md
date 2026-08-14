# engulf-clab-vrnetlab-build

Builds configured vrnetlab node images before `eclab deploy`. Install with
`python -m pip install engulf-clab-vrnetlab-build`; its vrnetlab checkout dependency
is installed automatically. Docker, `make`, and the selected vrnetlab builder
must be available.

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

Set the optional qcow2 or supported archive source in the runtime environment:

```bash
ECLAB_VRNETLAB_IMG_PATH=/images/router.qcow2 eclab deploy -t lab.clab.yml
```

`ECLAB_VRNETLAB_BUILD_JOBS` controls concurrent image builds and defaults to
`2`. Editions use their application-specific prefix. Set it to `1` for serial
builds or when builds compete for host memory or disk bandwidth.

The node `image` may differ from the native tag emitted by the builder. After a
successful build, the plugin retains the native tag and adds the requested node
image tag. `E_V_IMG_PATH` remains accepted as a compatibility alias. Editions
derive their prefix from short product metadata, falling back to full product
metadata (`acme clab` becomes `ACME_CLAB`).

## Source selection

The runtime `*_VRNETLAB_IMG_PATH` value may be a literal path, `$VARIABLE`, or
`${VARIABLE}`. A node `env` value of the same name is also accepted and takes
precedence over the runtime value.
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
