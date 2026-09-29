# Frozen $edition lab: $topology (lean)

This archive holds the lab source and a record of the exact $edition packages,
Containerlab, vrnetlab, and images it was frozen with. It carries no runtime:
you run it with the $edition already installed on this host.

## Requirements

- $edition installed; `packages.freeze.txt` lists the versions it was frozen with.
- Docker, and whatever Containerlab needs on this host.
- Network access for $edition to provision Containerlab, vrnetlab, and any
  images it cannot find locally.

## Start

```bash
$edition defrost ARCHIVE.tar.gz   # expand, compare versions, answer license prompts
cd <expanded directory>
./$launcher                       # deploys $topology
```

Defrost records every package or tool that differs from the frozen record in
`FREEZE-WARNINGS.txt`. The lab still runs; review those differences before
trusting a reproduction.

$licenses

## Operate

Arguments replace the default deploy, for example:

```bash
./$launcher destroy -t $topology
```

## Files

- `$topology` carries the freeze record under `x-engulf-clab-freeze`.
- `packages.freeze.txt` lists the producer's package versions.
- `images.freeze.json` records how each image is obtained.
- `initialize-env.sh` asks for values the producer kept private.
- `FREEZE-WARNINGS.txt` lists what freeze left out and what defrost found different.
