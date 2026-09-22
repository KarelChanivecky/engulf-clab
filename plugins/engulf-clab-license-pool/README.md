# engulf-clab-license-pool

Product-aware registered pools, automatic per-node license allocation,
selection strategies, and cleanup. Use `eclab init-license-pool` to register an
ordered pool for a Containerlab node kind.

The reusable, framework-neutral pool-manager and selector contracts are
published separately as
[`engulf-clab-license-pool-lib`](../engulf-clab-license-pool-lib/README.md).
It exposes pool-manager state and contracts; this package supplies the
standard `LicensePoolSelector` implementation plus the Engulf leases, state
store, topology editor, and lifecycle adapter.

- [Usage](USAGE.md) documents installation, configuration, lifecycle, security, and troubleshooting.
- [Contributing](CONTRIBUTING.md) documents implementation invariants and focused validation.
