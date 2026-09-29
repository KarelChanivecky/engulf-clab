# Frozen $edition lab: $topology (runtime)

This archive carries the complete $edition runtime the lab was frozen with:
every Python package as a wheel, the producer's Containerlab executable, and
its vrnetlab tree. Only Python is assumed on this host. Nothing is downloaded
to build the runtime.

## Requirements

- Linux on the same CPU architecture as the producer.
- A Python version listed in `python-versions.freeze.txt`.
- Docker, and whatever Containerlab needs on this host.
- Access to any images `images.freeze.json` leaves for you to supply.

## Start

With $edition already installed:

```bash
$edition defrost ARCHIVE.tar.gz
cd <expanded directory>
./$launcher                       # deploys $topology
```

With only Python:

```bash
tar xzf ARCHIVE.tar.gz
cd <archive directory>
./initialize-env.sh               # when the lab needs private values
./$launcher                       # deploys $topology
```

The first run creates `.eclab-venv`, installs the wheelhouse into it with
`pip install --no-index`, and installs the bundled Containerlab and vrnetlab
into it. Set `ECLAB_PYTHON` to choose the interpreter, for example
`ECLAB_PYTHON=python3.12 ./$launcher`.

If deploy reports that Containerlab requires root privileges, run
`./$launcher sudoless` as your normal user. This uses `sudo` to grant access to
the bundled Containerlab binary and Docker. Log out and back in to pick up the
new group memberships, then deploy again. Rebuilding `.eclab-venv` replaces
the binary, so repeat this setup afterward.

$licenses

## Operate

Arguments replace the default deploy, for example:

```bash
./$launcher destroy -t $topology
```

The launcher runs only the bundled tools and rejects Containerlab and
vrnetlab overrides. To rebuild the runtime, remove `.eclab-venv` and
`.eclab-freeze.env` and run the launcher again.

## Files

- `$topology` carries the freeze record under `x-engulf-clab-freeze`.
- `requirements.freeze.txt` and `wheelhouse/` are the locked Python runtime.
- `python-versions.freeze.txt` lists the Python versions the wheelhouse supports.
- `tools/containerlab/` and `tools/vrnetlab/` are the producer's tools.
- `images.freeze.json` records how each image is obtained.
- `FREEZE-WARNINGS.txt` lists what freeze left out.
