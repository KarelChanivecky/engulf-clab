# Frozen $edition lab: $topology (offline)

This archive carries everything the lab needs without network access: the
producer's $edition virtual environment, Containerlab, vrnetlab, and the
required images.

## Requirements

- Linux on the same CPU architecture as the producer.
- The Python version the producer ran; `.eclab-venv/pyvenv.cfg` names it.
- Docker, and whatever Containerlab needs on this host.
- `make`, `qemu-img`, and `qemu-system-x86_64` if you need to build opted-in
  vrnetlab images that the package does not supply.

## Start

```bash
./demo-offline.run
cd demo-offline
./$launcher                       # deploys $topology
```

Defrost prints its completion notes and warns about missing host dependencies
after extraction, with warnings last. `./check-dependencies.sh` repeats the
warning report without blocking. The launcher checks the requested operation before
running.

The frozen topology selects `images.freeze.json` through
`ECLAB_IMAGE_ARCHIVE_MANIFEST`. The active `engulf-clab-image-archive` provider
loads those snapshots during deploy or redeploy, including images owned by
service nodes generated from the frozen PKI catalog.

$licenses

Supply entitled vrnetlab VM images at deploy time with
`--eclab-vrnetlab-image NODE=PATH` when the topology needs them.

## Operate

Arguments replace the default deploy, for example:

```bash
./$launcher destroy -t $topology
```

The launcher uses only the bundled runtime, tools, and host Docker.
Python console commands in `.eclab-venv/bin/` use that directory's bundled
interpreter, including when run directly after extracting the archive.

## Files

- `freeze.json` records the freeze metadata separately from the Containerlab topology.
- `$topology` remains ordinary Containerlab YAML.
- `check-dependencies.sh` repeats the non-blocking host dependency report.
- `.eclab-venv/` is the bundled $edition runtime.
- `tools/containerlab/` and `tools/vrnetlab/` are the producer's tools.
- `images/` and `images.freeze.json` are the captured images and their record.
- `FREEZE-WARNINGS.txt` lists what freeze left out.
