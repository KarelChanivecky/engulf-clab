# FortiGate PKI injection

## Installation and activation

Install `engulf-clab-vrnetlab-fortigate-pki-injector` with
`engulf-clab-pki`. No additional topology switch is required. During deploy,
the plugin automatically injects authorized PKI paths into nodes whose resolved
Containerlab kind is exactly `fortinet_fortigate`.

PKI selection remains explicit through `ECLAB_PKI_MANIFEST`. Without that
selector, without this injector package, or for another node kind, the topology
is unchanged. Containerlab YAML remains the base language; see upstream
[`clab.schema.json`](https://github.com/srl-labs/containerlab/blob/main/schemas/clab.schema.json).

## Generated launcher environment

The plugin generates these vrnetlab-owned variables:

- `FOS_PKI_CA_CERTS`: semicolon-separated `refname:absolute_cert_path` entries
  for only the node's selected trusted-authority collection.
- `FOS_PKI_LOCAL_CERTS`: semicolon-separated
  `refname:absolute_key_path:absolute_cert_path` entries for node-authorized CA
  private identities and leaf identities issued to that node. The translator
  also supports projection-API certificate-only values as
  `refname:absolute_cert_path`.

The current PKI producer stages unencrypted PEM keys and does not project remote
certificates or generated CRLs, so the injector omits
`FOS_PKI_LOCAL_CERT_PASS_FILES`, `FOS_PKI_REMOTE_CERTS`, and `FOS_PKI_CRLS`.
All five names are reserved by the injector. A value already present in
topology defaults, a kind, a group, or an eligible node fails deployment
instead of being overwritten; the resolved declaration origin is reported.

The launcher imports CA certificates into FortiOS trust, configures local
certificate/key pairs (including deep-inspection CA pairs), and owns TFTP and
FortiOS CLI behavior. Environment values contain paths only; they never contain
certificate, key, or password bytes.

Every emitted entry has a nonempty refname. Authority declarations use their
catalog name, with `-VARIANT` appended for a non-default variant; issued
identities use their certificate declaration name. Refnames must be unique
within each variable. A collision fails preparation before topology mutation.
The launcher uses every explicit refname as the FortiOS object name, including
CA and remote-certificate entries. An empty refname falls back to the
certificate CN, but this injector always emits a nonempty declaration-derived
name.

Paths are absolute, staged before VM boot, and checked as regular files inside
the node's authorized view. Colons and semicolons are forbidden by the
projection API, so each generated entry has an unambiguous field count. The
injector never emits the legacy bare `path` or `key_path:cert_path` spellings.

## Mounts, lifecycle, and security

PKI mounts each authorized view read-only at `/mnt/eclab/pki` by default.
`ECLAB_PKI_MOUNT_TARGET` may override that absolute POSIX path in
`topology.defaults.env`, a kind, a group, or a node; node scope wins. PKI strips
the control from the derived environment, and injector paths use the resolved
target directly.

The injector runs after PKI and before the topology writer. Before mutation it
checks the typed projection, matching read-only bind, path containment, and each
staged regular file. It performs no generation, parsing, copying, state writes,
leases, or cleanup. PKI owns rollback and destroy cleanup.

A projection for a build-only node removed by an image provider is skipped.
Validation remains strict for every node still present in the deployable
topology.

Ordinary freeze archives retain source declarations but contain neither
generated `FOS_PKI_*` variables nor generated private material. PKI's explicit
encrypted secret-export flow remains the only private-material archive path.

## Troubleshooting

- “already defines injector-owned variable” — remove that `FOS_PKI_*` value;
  generated values cannot be merged or overridden.
- “does not match its PKI projection” — remove the conflicting bind or topology
  mutation and let PKI own the configured mount target.
- “projected PKI file is unavailable” — redeploy after correcting PKI staging or
  restoring the referenced generated material.
- “contains duplicate refname” — rename one colliding PKI declaration or
  variant so every FortiOS object in that category has a distinct name.
- No variables on a node — confirm the manifest is selected, this package is
  installed, and the resolved kind is `fortinet_fortigate`.
