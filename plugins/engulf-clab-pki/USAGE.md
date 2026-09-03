# PKI catalogs and node artifacts

## Install and activate

Install `engulf-clab-pki` in the same Python environment as `eclab`. The plugin
is discovered as package `engulf_clab.pki`, but remains a complete no-op until a
valid Containerlab topology selects a manifest:

```yaml
topology:
  defaults:
    env:
      ECLAB_PKI_MANIFEST: ./pki.yaml
  nodes:
    router:
      kind: linux
      image: alpine:latest
```

The path is relative to the selected topology, not the shell. It is removed only
from the generated topology. An empty `version: 1` manifest opts into public
artifacts from the global catalog. Without the selector, even an existing global
catalog cannot generate, mount, inject, or clean PKI state.

Set an absolute, normalized POSIX mount target in topology defaults or on one
node when `/mnt/eclab/pki` is unsuitable. Node scope wins:

```yaml
topology:
  defaults:
    env:
      ECLAB_PKI_MANIFEST: ./pki.yaml
      ECLAB_PKI_MOUNT_TARGET: /opt/lab/pki
  nodes:
    router:
      env:
        ECLAB_PKI_MOUNT_TARGET: /run/router-pki
```

The target cannot be `/`, contain `.` or `..` segments, repeated or trailing
separators, control characters, `:`, or `;`. PKI does not expand `~` or shell
variables. Both PKI controls are removed from the derived topology environment.

Containerlab YAML remains the base language; see the upstream
[`clab.schema.json`](https://github.com/srl-labs/containerlab/blob/main/schemas/clab.schema.json).
The selector is a convention layered on the valid `topology.defaults.env` field.

## Global and local catalogs

Run `eclab pki global path` to create the owner-private parent and print the
canonical `global.yaml`. `global init` writes a commented starter without
overwriting; `global edit` uses `VISUAL`, then `EDITOR`, validates a temporary
copy, detects concurrent changes, and commits atomically; `global validate`
parses without generating anything. Direct YAML edits are authoritative and are
reread on every invocation. Invalid edits fail closed.

`eclab pki effective -t lab.clab.yml` prints the merged graph with `global` or
`local` origins and no private material. Global catalogs may define `defaults`,
`profiles`, `stores`, and `authorities`; `nodes` and `services` are local-only.
Local defaults recursively overlay global defaults. Named profiles, stores, and
authorities replace same-named global objects in full and emit a warning.

Unqualified references search local then global. `global/name` and `local/name`
bypass shadowing. Global definitions resolve unqualified references globally and
cannot depend on local objects. Authority variants are named as
`authority/variant`, or `global/authority/variant` when scoped.

```yaml
version: 1
authorities:
  root-a: {}
  root-b: {}
  issuing:
    issuer: root-a
    variants:
      via-root-b:
        issuer: root-b
nodes:
  router:
    certificates:
      - name: tls
        issuer: issuing/via-root-b
```

The issuing variants share one key and subject but carry certificates signed by
different roots. Issuer cycles and missing references are rejected before host
state changes.

## Generation

Built-in compatibility defaults use RSA/SHA-256, self-sign authorities without
an issuer, apply CA constraints and CA key usage, and give leaf requests both
server/client authentication with node-derived CN and DNS SAN. Root,
intermediate, and leaf validity defaults are 7300, 3650, and 397 days.

An authority, reusable profile, or request may set:

```yaml
algorithm: {name: ecdsa, curve: secp384r1} # rsa/bits, ed25519, or ed448 too
subject:
  country: CA
  organization: Example Lab
  organizational_unit: Routing
  common_name: router.example.test
validity_days: 397
serial: 42
sans:
  dns: [router, router.example.test]
  ip: [192.0.2.10]
  email: [operator@example.test]
  uri: [spiffe://example.test/router]
basic_constraints: {ca: false}
key_usage: [digital_signature, key_encipherment]
extended_key_usage: [server_auth, client_auth]
aia: [{method: 1.3.6.1.5.5.7.48.2, uri: https://pki.example.test/ca.pem}]
crl_distribution_points: [https://pki.example.test/root.crl]
extensions:
  - {oid: 1.2.3.4, value: lab-extension, critical: false}
formats: [pem, der, pkcs12]
```

PEM produces an unencrypted PKCS#8 private key, SPKI public key, certificate,
chain, and full chain. DER, PKCS#12, and JKS are opt-in; JKS requires `keytool`
and an explicit `jks_password`. RSA keys smaller than 2048 bits and unsupported
curves/formats fail. ML-DSA requests fail explicitly when
the installed cryptography provider cannot support offline ML-DSA; PKI service
authorities do not accept it.

Global generations live under user state. Local generations and issued leaves
live under the topology workspace. A definition plus its issuer fingerprint
selects an immutable generation directory, so definition or signer changes
rotate rather than overwrite. Removed objects vanish from new views but retained
persistent history is not pruned. A named `directory` store requires an absolute
path and is protected by an authority lease.

## Node views and security

Every topology node in an opted-in lab gets a read-only bind at
`/mnt/eclab/pki` containing:

```text
inventory.json
trust/ca-bundle.pem
authorities/{global,local,effective}/AUTHORITY/VARIANT/...
issued/NODE/REQUEST/...
private/authorities/SCOPE/AUTHORITY/VARIANT/private-key.pem
```

All nodes receive public effective CA certificates, chains, and public keys.
Only a node declaring `authorities: [{name: root, private: true}]` gets that CA
key. Only the requesting node gets a leaf key. `inventory.json` records origins,
variants, fingerprints, and relative paths, never secrets. An existing bind to
the same target is rejected. The plugin neither installs trust nor decides how a
guest service consumes files.

After staging, PKI publishes an immutable per-node projection of authorized host
and in-container paths through `engulf-clab-pki-api`. Optional independently
installed injectors may consume it. PKI never discovers an injector and remains
a no-op for guest configuration by itself.

Install `engulf-clab-vrnetlab-fortigate-pki-injector` to automatically translate
projections for `kind: fortinet_fortigate` into the vrnetlab launcher's
`FOS_PKI_CA_CERTS` and `FOS_PKI_LOCAL_CERTS` path variables. Existing values for
any injector-owned `FOS_PKI_*` variable are rejected. Other node kinds remain
unchanged. See that package's `USAGE.md` for the complete launcher contract.

## Lifecycle and optional services

Generation and views occur during deploy preparation. Failure or interrupt
removes only directories created by that attempt. A provisioning journal allows
the next successful destroy to reconcile an interrupted preparation. Successful
destroy removes workspace views and ephemeral state; persistent workspace
history and all global material remain. `destroy --all` never erases the global
catalog or global authorities.

Services are absent by default. A local service block must explicitly name its
injected node; collisions fail. `ejbca` and `mariadb` have packaged default image
references, while other independent service types require `image`:

```yaml
services:
  central-ca: {type: ejbca, node: ejbca}
  database: {type: mariadb, node: pki-db, env: {MARIADB_DATABASE: ejbca}}
  responder: {type: ocsp, node: ocsp, image: example/ocsp:1}
```

Declarations recreate service nodes on defrost. Live database volumes and
EJBCA-only issuance history are not archive content.

## Freeze and defrost

Ordinary format-2 freeze vendors an external selected manifest as `pki.yaml`,
rebases the selector, and contains no generated private state. Explicit global
signers become fingerprint bindings when material exists, or regeneration intent
when it does not. Defrost prefers an exact matching recipient global authority;
use repeatable `--pki-authority BINDING=REF`, answer the prompt, or pass
`--no-pki-prompt` to retain an actionable unresolved marker. A same-name but
different identity is never selected merely by name. Defrost still accepts
legacy format 1; old readers reject format 2.

Exact identity preservation requires `freeze.exportable: true` on every
authority and leaf identity included, including referenced global signers, and
all material must already exist:

```text
eclab freeze --include-pki-secrets --pki-passphrase-file FILE
eclab defrost archive.tar.gz --pki-passphrase-file FILE
```

Without a file, an interactive hidden prompt is mandatory. No passphrase value
is accepted on the command line, logged, or archived. Identity payloads use a
random salt and nonce, scrypt-derived AES-256-GCM, and authenticated versioned
metadata. Wrong passphrases fail before publication. Restored identities remain
isolated inside the destination workspace and never overwrite recipient global
state. Referenced global identities are restored as local definitions. Service
volumes are never included.

## Troubleshooting

- “unresolved frozen PKI bindings” — defrost again with exact binding answers.
- “incompatible mount” — remove or relocate the existing `/mnt/eclab/pki` bind.
- “normalized absolute POSIX” — correct `ECLAB_PKI_MOUNT_TARGET`; do not use
  relative, root, delimited, or non-normalized paths.
- “authority issuer cycle” — break the recursive issuer relationship.
- “has no existing material” — deploy first before requesting identity export.
- “authentication failed” — the passphrase is wrong or the bundle was modified.
- A malformed direct global or local edit is never replaced with cached data;
  correct the YAML and rerun `pki global validate` or `pki effective`.
