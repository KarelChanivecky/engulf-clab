# Contributing

This distribution is a non-plugin resource installer. It must not publish any
`engulf.plugins.*` entry point or import an Engulf runtime. Its explicit
dependencies form the demo catalog; do not replace them with
`engulf-clab-all-plugins`, which would install the intentionally excluded WAN
and generated-skill plugins.

Keep `bundle/all-features.clab.yml`, `bundle/coverage.yaml`, package metadata,
and this documentation aligned. Internal bridge nodes must retain the
`<bridge>|segments` name and matching `network-mode: container:segments`.
FortiGate `port1` is management-only and must never be a link endpoint.

The installer may record an external FortiGate image path, but must never copy,
inspect, archive, or hash that image. `inputs/licenses/` must be created empty;
do not add a placeholder file because every regular top-level file is a pool
candidate. Never add passwords, licenses, private keys, generated certificates,
or private repository locations.

Validate with:

```bash
.venv/bin/python -m pytest -q demo-lab/tests
.venv/bin/python -m build --no-isolation demo-lab
.venv/bin/python -m twine check demo-lab/dist/*
```

Also validate the topology against the exact active generated
`clab.schema.json` and run `make check-skill` when the repository documentation
or runtime package inventory changes.
