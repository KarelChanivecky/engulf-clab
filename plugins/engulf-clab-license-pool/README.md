# engulf-clab-license-pool

Product-aware registered pools, automatic per-node license allocation,
selection strategies, inspection, and cleanup. Use `eclab init-license-pool` to
register an ordered pool for a Containerlab node kind and
`eclab inspect-license-pool` to view its metadata and allocation counts.

The reusable, framework-neutral pool-manager and selector contracts are
published separately as
[`engulf-clab-license-pool-lib`](../engulf-clab-license-pool-lib/README.md).
It exposes pool-manager state and contracts; this package supplies the
standard `LicensePoolSelector` implementation plus the Engulf leases, state
store, topology editor, and lifecycle adapter.

Pool-side metadata and typed variable declarations use the
[`engulf-clab-license-pool-api`](../engulf-clab-license-pool-api/README.md);
the shared command owns prompts, namespaced `.lic-pool` writes, and registration.

- [Usage](USAGE.md) documents installation, configuration, lifecycle, security, and troubleshooting.
- [Contributing](CONTRIBUTING.md) documents implementation invariants and focused validation.
