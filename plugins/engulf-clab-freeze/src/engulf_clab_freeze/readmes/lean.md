# Frozen $edition lab: $topology (lean)

This archive holds the lab source and a record of the exact $edition packages,
Containerlab, vrnetlab, and images it was frozen with. It carries no runtime:
you run it with the $edition already installed on this host.

## Requirements

- $edition installed; `packages.freeze.txt` lists the versions it was frozen with.
- Docker, and whatever Containerlab needs on this host.
- `make`, `qemu-img`, and `qemu-system-x86_64` if you need to build opted-in
  vrnetlab images that are not already available.
- Network access for $edition to provision Containerlab, vrnetlab, and any
  images it cannot find locally.

## Start

```bash
$edition defrost ARCHIVE.tar.gz   # expand, compare versions, answer license prompts
cd <expanded directory>
./$launcher                       # deploys $topology
```

The runtime package form wraps a normal lab archive beside `runtime/` and a
`defrost.sh` script. That script uses the bundled edition to run normal
defrost, which initializes recipient environment values, resolves licenses,
and warns about missing host dependencies without blocking defrost. The restored
lab keeps `check-dependencies.sh` for repeatable reports; its launcher checks
operation-specific dependencies before running.

Defrost records every package or tool that differs from the frozen record in
`FREEZE-WARNINGS.txt`. The lab still runs; review those differences before
trusting a reproduction.

Supply entitled vrnetlab VM images at deploy time with
`--eclab-vrnetlab-image NODE=PATH` when the topology needs them.

$licenses

## Operate

Arguments replace the default deploy, for example:

```bash
./$launcher destroy -t $topology
```

## Files

- `freeze.json` records the freeze metadata separately from the Containerlab topology.
- `$topology` remains ordinary Containerlab YAML.
- Runtime-bundle defrost includes `check-dependencies.sh` to repeat the dependency report.
- `packages.freeze.txt` lists the producer's package versions.
- `images.freeze.json` records how each image is obtained.
- `initialize-env.sh` asks for values the producer kept private.
- `FREEZE-WARNINGS.txt` lists what freeze left out and what defrost found different.
