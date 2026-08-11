# engulf-clab-vrnetlab

`engulf-clab-vrnetlab` is the vrnetlab-build plugin. It builds configured images before
`engulf-clab deploy` starts Containerlab.

Opt a node in with a vrnetlab builder path and an image source:

```yaml
name: my-lab

topology:
  nodes:
    fgt:
      kind: fortinet_fortigate
      image: vrnetlab/vr-fortios:8.0.0
      env:
        ENGULF_CLAB_VRNETLAB_TYPE: fortinet/fortigate
        ENGULF_CLAB_VRNETLAB_IMG_PATH: $IMAGE_SOURCE
```

The builder type is resolved beneath a prepared vrnetlab checkout. This package
has a hard dependency on `engulf-clab-ensure-vrnetlab`, which runs first and
publishes context `engulf_clab.vrnetlab.path`. The selected builder
directory must contain a `Makefile`; all checkout discovery and cloning belongs
to the ensure plugin.

The prefix derives from the launcher `display_name`. An edition named
`acme-clab` uses `ACME_CLAB_VRNETLAB_TYPE` and
`ACME_CLAB_VRNETLAB_IMG_PATH`.

## Image source lookup

`ENGULF_CLAB_VRNETLAB_IMG_PATH` may be a literal path or an exact `$VARIABLE` or
`${VARIABLE}` reference. Relative paths are resolved from the topology
directory, which permits a lab package to carry its image source.

For lab `my-lab`, node `fgt-1`, and `$IMAGE_SOURCE`, process variables are
tried in this order:

```text
MY_LAB_FGT_1_IMAGE_SOURCE
MY_LAB_IMAGE_SOURCE
IMAGE_SOURCE
```

Lab, node, and variable components are uppercased and non-alphanumeric runs
become underscores. This lets several labs or nodes use the same portable
topology while selecting different source images.

When the node does not set `ENGULF_CLAB_VRNETLAB_IMG_PATH`, the invocation
environment may set the same variable. The official launcher also accepts the
legacy `ECLAB_VRNETLAB_IMG_PATH` and `E_V_IMG_PATH` aliases. Their
values use the same literal-path and variable-reference rules.

Supported sources are `.qcow2`, `.zip`, `.tar`, `.tar.gz`, and `.tgz`.
Archives must contain exactly one qcow2. The qcow2 basename is preserved when
it is staged because vrnetlab builders derive their native image tag from that
name.

## Build behavior

The node's resolved `image` must be the native tag produced by its vrnetlab
builder. The plugin does not retag builder output or override the version.
Existing qcow2 files in the builder directory are moved aside during the
build and restored afterward. Stale `docker/*.qcow2*` artifacts are removed
before and after `make`.

If no source resolves and the node image already exists locally, the plugin
uses it. If neither a source nor a local image exists, deployment stops.

Build identity consists of the target image, qcow2 SHA-256 and basename,
vrnetlab checkout fingerprint, and builder type. Fingerprints are stored as
`vrnetlab-images.json` in this plugin's Engulf `StateScope.USER` store. User
scope is intentional because local Docker tags are shared across labs. Engulf
provides the storage location, ownership handling, locking, and atomic writes.

Each build holds leases for its Docker image tag and resolved vrnetlab builder
directory. Fingerprint reads and updates use short state transactions; an update
re-reads and merges the current record before saving, so independent image builds
cannot discard each other's fingerprints.
