# Agent instructions

- Keep plugin ID `engulf_clab.vrnetlab_fortigate_pki_injector` and automatic activation stable.
- Consume only `engulf-clab-pki-api` projections; never parse catalogs or certificates.
- Mutate only derived `fortinet_fortigate` node environments during deploy preparation.
- Reject every injector-owned environment collision and validate staged files and binds first.
- Preserve package-declared PKI-before and writer-after ordering.
- Keep host state, leases, copying, TFTP, FortiOS commands, and cleanup out of this package.
