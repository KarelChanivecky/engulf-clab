# Agent instructions

- Keep plugin ID `engulf_clab.vrnetlab_fortigate_pki_injector` and automatic activation stable.
- Consume only `engulf-clab-pki-api` projections; never parse catalogs or certificates.
- Mutate only derived `fortinet_fortigate` node environments during deploy preparation.
- Skip projections for build-only nodes already removed from the deployable topology.
- Emit mandatory, stable refnames before every staged path entry and reject category-local collisions.
- Mutate generated environment leaf keys, never the complete node `env` mapping.
- Reject every injector-owned environment collision and validate staged files and binds first.
- Preserve package-declared PKI-before and writer-after ordering.
- Keep host state, leases, copying, TFTP, FortiOS commands, and cleanup out of this package.
