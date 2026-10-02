# Frozen $edition lab: $topology (runtime)

The `--eclab-with-runtime` package is an executable `.run` containing
`runtime/`, a normal `lab.tgz`, and `defrost.sh`. Running the package performs
the whole workflow: it builds the pinned $edition environment from the included
wheelhouse when needed, then runs ordinary defrost. Defrost runs
`initialize-env.sh`, prompts for recipient license values, and places the
runtime in the restored lab. The default output is `./<package-name>`.
If no license pool is registered, defrost offers to create a pool directory
and initialize it with the edition's `init-license-pool` command. The new pool
starts empty; add entitled license files afterward. Read `FREEZE-README.md` in
the restored lab for the lab-specific instructions to run it.

## Requirements

- Linux on the same CPU architecture as the producer.
- A Python version listed in `python-versions.freeze.txt`.
- Docker, and whatever Containerlab needs on this host.
- `make`, `qemu-img`, and `qemu-system-x86_64` if you need to build opted-in
  vrnetlab images that the package does not supply.
- Access to any images `images.freeze.json` leaves for you to supply.

## Start

```bash
./demo-runtime.run
cd demo-runtime
./$launcher                       # deploys $topology
```

Pass an output directory as the `.run` command's first argument to extract
elsewhere, for example `./demo-runtime.run restored`.

The bundle does not need an installed eclab. It needs a Python version listed
in `runtime/python-versions.freeze.txt` to build the venv. Defrost warns about
missing host dependencies without blocking. Its actionable notes and dependency
report appear after the runtime setup output, with warnings last.
Repeat the report from `restored` with `./check-dependencies.sh`. The restored
launcher checks the requested operation before it runs.

The package's `defrost.sh` builds `.eclab-venv` with `pip install --no-index`
from `runtime/wheelhouse/`, then defrost copies it with the bundled Containerlab
and vrnetlab files into the restored lab. Set `ECLAB_PYTHON` to choose the
interpreter, for example `ECLAB_PYTHON=python3.12 ./demo-runtime.run`.
Pass `--eclab-no-runtime` to defrost if the lab should build its runtime on
first launch instead of copying the prepared venv.

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

- `freeze.json` records the freeze metadata separately from the Containerlab topology.
- `$topology` remains ordinary Containerlab YAML.
- `check-dependencies.sh` repeats the non-blocking host dependency report.
- `requirements.freeze.txt` and `wheelhouse/` are the locked Python runtime.
- `python-versions.freeze.txt` lists the Python versions the wheelhouse supports.
- `tools/containerlab/` and `tools/vrnetlab/` are the producer's tools.
- `images.freeze.json` records how each image is obtained.
- `FREEZE-WARNINGS.txt` lists what freeze left out.
