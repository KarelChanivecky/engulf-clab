# engulf-clab-freeze

Portable lab archive creation, expansion, and recipient workflows.

Default freeze includes image dependencies unavailable from a registry or a
complete included build recipe. `--lean` substitutes recipient variables;
`--offline` also packages the runtime, tools, and network-dependent images.

New archives use format 2 and optional feature packages extend staging through
`engulf-clab-freeze-api`; defrost also accepts legacy format 1 archives.

- [Usage](USAGE.md) documents installation, configuration, lifecycle, security, and troubleshooting.
- [Contributing](CONTRIBUTING.md) documents implementation invariants and focused validation.
