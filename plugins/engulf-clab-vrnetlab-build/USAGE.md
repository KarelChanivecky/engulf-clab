# Shared builder

Install `engulf-clab-vrnetlab-build` with at least one source provider. Its
plugin ID is `engulf_clab.vrnetlab_build`. The package provides the one shared
builder and Docker image recipe adapter; it has no source-selection flags or
provider-specific YAML controls. Source providers publish absolute input paths
and their plugin IDs through `engulf-clab-vrnetlab-build-api`. This builder
resolves the opted-in nodes, stages source files safely, runs the selected
vrnetlab Makefile, and offers the resulting tag to the Docker image build graph.

Nodes that fall back to the API's `default` source must all use the same
`ECLAB_VRNETLAB_TYPE`. `fortinet/fortigate` and `fortinet/fortiproxy` nodes
cannot share one default source because the FortiGate image is not a FortiProxy
image. Providers can publish exact per-node sources when a topology uses
multiple builder types.

The builder requires a prepared vrnetlab checkout, Docker access, `make`, and
`qemu-img` for sources that need image inspection or conversion. It serializes
work that targets one builder directory, protects existing requested Docker
tags, restores builder qcow2 files, and fingerprints successful output in
user-scoped Engulf state.

When replacing an image tag, the builder checks whether running containers use
the previous image before removing its temporary backup tag. If any do, it
keeps the successfully built image under the requested tag, retains the old
image under the printed backup tag, and warns with the container names. If
Docker refuses backup cleanup for another reason, the builder also retains the
backup and includes Docker's error detail in the warning. Stop or destroy any
dependent containers before removing the backup with the suggested
`docker image rm` command.

Choose a lab-unique requested image tag. Docker tags are host-global and a
shared mutable tag couples otherwise independent labs. Destroy does not remove
built images or build fingerprints.

For local source syntax, install `engulf-clab-vrnetlab-static-image-provider`
and read its `USAGE.md`. Other providers may create or download sources and
publish their paths and plugin IDs through the same API. The builder publishes
per-node source-provider IDs, builder types, and qcow2 SHA-256 values in
`VRNETLAB_SOURCE_PROVENANCE_CONTEXT`; it persists no source paths. The Docker
image-build adapter separately records which Docker provider resolved each
image. During preparation, an informational log records each source-backed
node's requested Docker image, resolved source path, source-provider ID, and
the Docker image provider ID (`org.engulf.docker.vrnetlab-build`). Nodes using
an already-installed image without a source are logged as having no vrnetlab
image provider selected. Dynamic `eclab --help` and the plugin list show which
providers are installed for the selected edition.

After a successful single-lab `eclab inspect -t TOPOLOGY`, eclab reports the
persisted node and image reference, vrnetlab builder type, source-provider ID,
and source SHA-256 for each vrnetlab image in that lab. It does not expose the
source path.
