# PKI usage

PKI is enabled when `topology.defaults.env.ECLAB_PKI_MANIFEST` selects a
topology-relative manifest. Only manifest `version: 2` is accepted; version 1 is rejected with
a migration message.

## Catalog and node requests

Containerlab YAML remains the topology language. A v2 manifest declares reusable profiles,
stores, authorities, and named leaf certificates:

```yaml
version: 2
profiles:
  tls-client: {extended_key_usage: [client_auth]}
authorities:
  issuing: {issuer: root}
  root: {}
certificates:
  workstation-user:
    issuer: issuing
    profile: tls-client
    subject: {common_name: workstation-user}
```

Nodes request identities through comma-separated environment lists:

```yaml
topology:
  defaults:
    env: {ECLAB_PKI_MANIFEST: ./pki.yaml}
  nodes:
    workstation:
      env:
        ECLAB_PKI_CERTIFICATES: workstation-user
        ECLAB_PKI_PRIVATE_AUTHORITIES: inspection-ca
```

Both lists accept `local/name`, `global/name`, or unqualified references. Request,
trust, and mount-target env values inherit with `defaults < kind < group < node`.
The winning list replaces the complete lower-level list; an empty or null request
value requests nothing. The manifest selector remains a defaults-only lab opt-in.
References are resolved before duplicate checking. Local named
objects shadow global objects by whole object; global certificate declarations may refer only
to global profiles and authorities. Omitted certificate CNs retain the requesting node-name
default. Use distinct declarations for distinct fixed SANs. When `not_before` is omitted,
generated certificates start two days before generation time to tolerate clock skew; set
`not_before` explicitly for a different validity start.

The request variables are removed from every declaration level in the derived
topology, including shadowed and unused kind/group definitions. PKI injects
`ECLAB_PKI_ROOT` with the resolved read-only mount target and rejects a user-authored collision.
`ECLAB_PKI_MOUNT_TARGET` changes that normalized absolute target and is also consumed.

## Trust and inventory

`ECLAB_PKI_TRUST_MODE=all|none` defaults to `all`; all selects natural root anchors only.
`ECLAB_PKI_TRUST_INCLUDE` may explicitly promote an intermediate, and
`ECLAB_PKI_TRUST_EXCLUDE` is applied last. Every public authority remains visible, while
`trust/ca-bundle.pem` contains only the node's selected trust.

`inventory.json` version 2 lists available public authorities, trusted authorities, requested
private authorities, and issued identities. Every identity has a canonical `global/name` or
`local/name` ID, fingerprint, formats, and mount-relative path. Private keys occur only in the
requesting node's view.

Optional service declarations inject independent service nodes. The directory
recipe uses the pinned public `osixia/openldap:1.5.0` image; the former
`bitnami/openldap:latest` repository no longer publishes free Docker Hub tags.

## Lifecycle, state, and security

Deploy and single-source redeploy both stage PKI. Persistent authorities live in Engulf user/workspace state; generated leaves and views live in
workspace state. Generation occurs during preparation under leases and is journaled. Failed
preparation unwinds only paths created by that attempt. If Containerlab starts but deployment
fails, staged paths remain readable by any partial containers and are journaled for cleanup by a
successful `destroy`. A failure before the process starts unwinds immediately. Successful
`destroy` removes views and ephemeral state, not persistent identity history.

`eclab pki global path|init|edit|validate` manages the global v2 catalog.
`eclab pki effective -t TOPOLOGY` prints the merged origin-labelled catalog plus resolved node
requests without generating keys.

Freeze vendors the v2 manifest. Ordinary archives contain no private material. Optional
`--include-pki-secrets --pki-passphrase-file FILE` encrypts only declarations explicitly marked
`freeze.exportable`; defrost verifies fingerprints and restores canonical declaration identities.
Exported user authorities become local identities in the recipient. Their explicit
trust and private-authority requests are rebased with them, so restoring the
encrypted archive does not require the producer's user catalog.

Treat mounted private keys as secrets. Do not place credentials or private-key contents in
catalogs. CRL, OCSP, and managed certificate-database namespaces are reserved and have no
enforcement behavior in this release.

## Troubleshooting

- An unknown or ambiguous reference fails before material generation.
- Duplicate aliases resolving to one canonical object fail rather than being silently merged.
- A bind already targeting the PKI mount or a user-defined `ECLAB_PKI_ROOT` fails as a collision.
- Inspect installed behavior with `eclab --help`, `eclab --engulf-plugin-list`, and
  `eclab pki effective -t TOPOLOGY`.
