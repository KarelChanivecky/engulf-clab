# Frozen $edition lab: $topology (offline)

This archive carries everything the lab needs without network access: the
producer's $edition virtual environment, Containerlab, vrnetlab, and the
required images.

## Requirements

- Linux on the same CPU architecture as the producer.
- The Python version the producer ran; `.eclab-venv/pyvenv.cfg` names it.
- Docker, and whatever Containerlab needs on this host.

## Start

```bash
$edition defrost ARCHIVE.tar.gz
cd <expanded directory>
./$launcher                       # deploys $topology
```

The frozen topology points each image node at its bundled archive. The
installed `engulf-clab-image-archive` plugin loads it during deploy. If that
plugin is absent from the frozen runtime, freeze includes `load-images.sh`; run
it once before deploy.

$licenses

## Operate

Arguments replace the default deploy, for example:

```bash
./$launcher destroy -t $topology
```

The launcher uses only the bundled runtime, tools, and host Docker.

## Files

- `$topology` carries the freeze record under `x-engulf-clab-freeze`.
- `.eclab-venv/` is the bundled $edition runtime.
- `tools/containerlab/` and `tools/vrnetlab/` are the producer's tools.
- `images/` and `images.freeze.json` are the captured images and their record.
- `FREEZE-WARNINGS.txt` lists what freeze left out.
