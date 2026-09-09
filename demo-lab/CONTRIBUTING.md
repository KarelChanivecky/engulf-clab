# Contributing

This distribution is a non-plugin resource installer. It must not publish any
`engulf.plugins.*` entry point or import an Engulf runtime. Its explicit
dependencies form the demo catalog; do not replace them with
`engulf-clab-all-plugins`.

Keep `bundle/all-features.clab.yml`, `bundle/coverage.yaml`, package metadata,
and the documentation aligned. The lab must stay deployable without a
proprietary VM image, a license, or operator-specific runtime input. Internal
bridge nodes retain the `<bridge>|segments` name and matching
`network-mode: container:segments`. Bridge endpoints in the shared `segments`
namespace need unique interface names across all synthetic bridges.

The router is intentionally simple: `eth1` is `10.10.10.1/24`, `eth2` is
`192.0.2.1/24`, and `eth3` is the packaged WAN-access uplink. Keep direct
client/DMZ forwarding independent of uplink availability.

Install `busybox-extras` explicitly in the archive-built Alpine image; the base
BusyBox build does not provide its `httpd` applet. Use one `echo` command per
generated `/etc/hosts` line because Containerlab exec parsing consumes a
backslash in a shell `printf` format. Document inspection by lab name because
build-only nodes are absent from the deployed topology.

Never add passwords, licenses, private keys, generated certificates, private
repository locations, or proprietary VM inputs.

Validate with:

```bash
.venv/bin/python -m pytest -q demo-lab/tests
.venv/bin/python -m build --no-isolation demo-lab
.venv/bin/python -m twine check demo-lab/dist/*
```

Also validate the topology against the exact active generated
`clab.schema.json` and run `make check-skill` when repository documentation or
the runtime package inventory changes.
