# Shared builder

Install `engulf-clab-vrnetlab-build` with at least one source provider. Its
plugin ID is `engulf_clab.vrnetlab_build`. The package provides the one shared
builder and Docker image recipe adapter; it has no source-selection flags or
provider-specific YAML controls. Source providers publish absolute input paths
through `engulf-clab-vrnetlab-build-api`; this builder resolves the opted-in
nodes, stages source files safely, runs the selected vrnetlab Makefile, and
offers the resulting tag to the Docker image build graph.

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

Choose a lab-unique requested image tag. Docker tags are host-global and a
shared mutable tag couples otherwise independent labs. Destroy does not remove
built images or build fingerprints.

For local source syntax, install `engulf-clab-vrnetlab-static-image-provider`
and read its `USAGE.md`. Other providers may create or download sources and
publish their paths through the same API. Dynamic `eclab --help` and the plugin
list show which providers are installed for the selected edition.
