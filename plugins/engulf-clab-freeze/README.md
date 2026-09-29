# engulf-clab-freeze

Portable lab archive creation, expansion, and recipient workflows.

Default freeze records compatibility without bundled runtime or captured image
snapshots. Authored files named by `ECLAB_IMAGE_ARCHIVE` remain part of the lab
source copy when they are in scope and survive the freeze exclusions.
`--eclab-with-runtime` bundles the producer's Containerlab, vrnetlab, and a
complete wheelhouse the recipient installs into a lab venv with only Python;
`--eclab-offline` also bundles the Python runtime and images.

If a defrosted runtime lab reports that Containerlab requires root privileges,
run `./run-eclab.sh sudoless` from the expanded lab as your normal user, then
log out and back in before deploying. Repeat after rebuilding `.eclab-venv`.

New archives use format 3 and optional feature packages extend staging through
`engulf-clab-freeze-api`; defrost also accepts legacy format 1 and 2 archives.

- [Usage](USAGE.md) documents installation, configuration, lifecycle, security, and troubleshooting.
- [Contributing](CONTRIBUTING.md) documents implementation invariants and focused validation.
