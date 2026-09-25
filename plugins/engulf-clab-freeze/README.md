# engulf-clab-freeze

Portable lab archive creation, expansion, and recipient workflows.

Default freeze records compatibility without bundled runtime or captured image
snapshots. Authored files named by `ECLAB_IMAGE_ARCHIVE` remain part of the lab
source copy when they are in scope and survive the freeze exclusions.
`--eclab-with-runtime` adds pinned tools and a wheelhouse; `--offline` also
bundles the runtime, tools, and images.

New archives use format 3 and optional feature packages extend staging through
`engulf-clab-freeze-api`; defrost also accepts legacy format 1 and 2 archives.

- [Usage](USAGE.md) documents installation, configuration, lifecycle, security, and troubleshooting.
- [Contributing](CONTRIBUTING.md) documents implementation invariants and focused validation.
