# PKI-to-vrnetlab injector contract

## Status and boundary

This document records the implemented contributor boundary. Operator-facing
behavior is summarized in the PKI and FortiGate injector `USAGE.md` files. The
`FOS_*` contract remains owned by the FortiGate vrnetlab launcher.

The integration uses dependency inversion. PKI publishes a typed description of
the files it has already authorized and staged for each node. A separately
installed, image-family-specific plugin translates that description into the
launcher's input language:

```text
vrnetlab FortiGate launcher
            ↑ FOS_* path contract
FortiGate PKI injector
            ↓ typed node projection
engulf-clab-pki
```

The packages are:

- `engulf-clab-pki-api`, an import-only contract package with immutable
  projection types and the shared invocation-context key;
- `engulf-clab-pki`, the existing generator and staging owner, extended to
  publish projections after staging; and
- `engulf-clab-vrnetlab-fortigate-pki-injector`, an optional topology mutator
  with plugin ID `engulf_clab.vrnetlab_fortigate_pki_injector`.

The PKI plugin must not import, discover, configure, or branch on an injector.
The FortiGate injector depends on the projection API and PKI plugin, never the
reverse. A future image family gets a separate injector and has no effect on
PKI's generation or staging logic.

FortiGate certificate installation is a vrnetlab concern. The environment
variable names and grammar are repeated below so the injector boundary is
testable, but their canonical definition, escaping rules, transfer mechanism,
FortiOS object names, and installation sequence remain owned by the FortiGate
vrnetlab launcher.

## Projection API

`engulf-clab-pki-api` exposes the stable context key
`engulf_clab.pki.node_projections.v2` plus frozen, slotted value types. The
public contract has the following logical shape:

```text
PkiNodeProjections
  nodes: tuple[NodePkiProjection, ...]

NodePkiProjection
  node_name: str
  node_kind: str
  staged_view: absolute host Path
  mount_target: normalized absolute PurePosixPath
  public_authorities: tuple[PublicAuthorityProjection, ...]
  requested_authorities: tuple[RequestedAuthorityProjection, ...]
  issued_identities: tuple[IssuedIdentityProjection, ...]

PublicAuthorityProjection
  scope, name, variant, fingerprint_sha256: str
  classification: trust_anchor | intermediate
  certificate, chain, full_chain: absolute in-container paths

RequestedAuthorityProjection
  scope, name, variant, fingerprint_sha256: str
  certificate, chain, full_chain: absolute in-container paths
  private_key: absolute in-container path | None

IssuedIdentityProjection
  request_name, fingerprint_sha256: str
  certificate, private_key, chain, full_chain: absolute in-container paths
```

Each artifact field is a `ProjectedFile` pairing its absolute host path with its
absolute in-container `PurePosixPath`. All public collections are tuples, enums
are closed, and the types reject invalid values during construction. The API
does not depend on `engulf`, the PKI implementation package, a vrnetlab package,
or a specific image family.

The node projection contains only paths the node is authorized to read through
its staged view. `staged_view` lets an injector verify that a projected file
exists and remains below the bind source; it is never emitted into the topology
or passed to the image. Every artifact path passed to an image is an absolute
POSIX path below `mount_target`. A projection contains no certificate bytes,
key bytes, passwords, catalog objects, service credentials, or mutable topology
objects.

PKI publishes exactly one `PkiNodeProjections` value after material generation,
view staging, and mount mutation succeed. Publication is invocation-scoped. A
missing context means no PKI-enabled deploy was prepared and is not an error.
PKI remains responsible for consuming or otherwise accounting for its context
when no injector is installed, so the optional consumer cannot create an
unused-context diagnostic.

### Projection contents

For every topology node in an opted-in deploy, PKI publishes:

- every public variant of every available authority, identified by resolved
  scope, name, variant, and certificate fingerprint;
- every authority identity explicitly requested by that node, including a
  private-key path only when that request set `private: true`; and
- every leaf identity issued for that node, including its certificate, private
  key, chain, and full-chain paths.

An effective authority with no resolved issuer is a trust anchor. An effective
authority with a resolved issuer is an intermediate. Consequently, a
cross-signed variant is an intermediate even when another variant of the same
authority identity is self-signed. Classification comes from the resolved
catalog graph; an injector must not parse certificates to infer it.

Explicit authority requests are preserved separately from the public-effective
set because they express node intent and may refer to a scope hidden by normal
effective-name resolution. A private-key path is absent, rather than empty,
unless that exact node was authorized to receive the key. Leaf identities are
projected only for their requesting node.

PKI produces projection tuples in canonical order: node name, then resolved
scope/name/variant/fingerprint for authorities, and request name/fingerprint for
leaves. It removes exact duplicate identities by certificate fingerprint within
each semantic category. When repeated requested-authority entries have the same
fingerprint, PKI retains the authorized private-key path if any one of those
requests authorized it, then uses the lexicographically first resolved identity
as the canonical entry. Entries with the same identity but different variants
remain distinct when their certificate fingerprints differ. This makes roots,
intermediates, cross-signed variants, and repeated references deterministic
without asking an injector to understand the catalog.

## Mount target control

`ECLAB_PKI_MOUNT_TARGET` is an eclab-only convention accepted in defaults,
kind, group, or node env. It follows `defaults < kind < group < node` through
the shared effective-node API. If absent, the effective target remains
`/mnt/eclab/pki`.

PKI, not an injector, resolves and validates the value. The effective value must
be a non-empty, normalized absolute POSIX path. Reject `/`, `.` and `..` path
segments, repeated separators, a trailing separator, NUL or control characters,
and `:` because the value is used as a Containerlab bind target. Reject a target
already occupied by an incompatible string or structured bind. Do not expand
shell variables, `~`, or platform-native path syntax.

PKI removes `ECLAB_PKI_MOUNT_TARGET` from both defaults and node environments in
the derived topology, just as it removes `ECLAB_PKI_MANIFEST`. It adds the
read-only node view bind at the resolved target and builds all projected guest
paths from that same value. The source declaration remains in the user's
topology and therefore remains reproducible through ordinary freeze/defrost.

There is deliberately no additional root environment variable. Injector output
contains absolute guest paths, so the FortiGate launcher does not need to know
the default mount target or interpret an eclab setting.

The vrnetlab image and launcher must never receive or interpret
`ECLAB_PKI_MANIFEST`, `ECLAB_PKI_MOUNT_TARGET`, catalog scopes or profiles,
`inventory.json`, Engulf plugin IDs, host state paths, or the conventional
`/mnt/eclab/pki` default. The only coupling from the injector to that image is
the companion `FOS_*` path grammar.

## FortiGate injector

The optional injector activates during deploy preparation only when all of the
following are true:

1. the PKI projection context exists;
2. a projected node still exists in the shared topology session; and
3. that node's resolved Containerlab kind is exactly `fortinet_fortigate`.

A missing PKI context, a topology without PKI selection, an absent injector
package, or any other node kind is a no-op. Installation of the injector is the
only feature switch; no second topology control is needed.

For each eligible node, the injector validates the projection and translates
its non-empty semantic categories into the variables defined by the companion
vrnetlab FortiGate contract. It mutates only that node's derived `env` mapping.
It performs no certificate generation or parsing, file copying, TFTP serving,
guest installation, state transactions, lease acquisition, or persistent-state
cleanup.

### FortiGate launcher contract

The injector targets this exact launcher-owned environment contract:

| Variable | Grammar | FortiOS effect |
| --- | --- | --- |
| `FOS_PKI_CA_CERTS` | `refname:path`, with entries separated by `;` | Reads each PEM and configures `config vpn certificate ca`, `edit "<refname>"`, and `set ca "<PEM>"`. An empty refname falls back to the certificate CN. |
| `FOS_PKI_LOCAL_CERTS` | `refname:key_path:cert_path` or `refname:cert_path`, with entries separated by `;` | Reads the referenced contents and configures `config vpn certificate local`, `edit "<refname>"`, `set private-key "<PEM>"` when present, and `set certificate "<PEM>"`. The same mechanism handles ordinary server identities and CA keypairs used for deep inspection. |
| `FOS_PKI_LOCAL_CERT_PASS_FILES` | `path;path;...`, optional | Reads each companion file and supplies its content through `set password <contents>`. Entries correspond positionally to the encrypted-key entries, not to every entry, in `FOS_PKI_LOCAL_CERTS`. |
| `FOS_PKI_REMOTE_CERTS` | `refname:path`, with entries separated by `;` | Reads each PEM and configures `config vpn certificate remote`, `edit "<refname>"`, and `set remote "<PEM>"`. An empty refname falls back to the certificate CN. |
| `FOS_PKI_CRLS` | `refname:path`, with entries separated by `;` | Reads the PEM body, base64-encodes it, and sets `crl` on the explicitly named object. The launcher selects `config vpn certificate crl` or the release-dependent `config certificate crl` after inspecting `get system status`. |

`path` always means an absolute in-container path projected below the node's PKI
mount. A semicolon separates entries. Every entry begins with a mandatory
refname and colon; further colons separate the private-key and certificate paths
for a local keypair. PKI's controlled mount, artifact names, and refnames
therefore must not contain either delimiter.
The launcher reads file contents only after receiving these paths; environment
values themselves remain paths-only.

The injector always emits an explicit refname derived from the catalog role:
authority name plus a non-default variant suffix, or the issued certificate
declaration name. It rejects duplicate refnames within a category. It never
emits the fallback empty-refname spelling, a colon-free path, or the ambiguous
legacy `key_path:cert_path` spelling.

The initial projection maps to the contract as follows:

- `FOS_PKI_CA_CERTS` receives only the node-selected trusted authorities,
  deduplicated by fingerprint in canonical projection order and encoded as
  `refname:cert_path`.
- `FOS_PKI_LOCAL_CERTS` receives each explicitly requested authority that has an
  authorized private-key path and every issued leaf identity, encoded as
  `refname:key_path:cert_path`. A projected certificate-only local value is
  encoded as `refname:cert_path`. This is also how an authorized CA identity
  reaches the launcher's deep-inspection mechanism.
- `FOS_PKI_LOCAL_CERT_PASS_FILES` is omitted because the initial PKI projection
  stages unencrypted PEM private keys. Supporting encrypted private keys later
  requires an explicit, node-authorized passphrase-file path in the typed API;
  the injector must never infer encryption by parsing a key.
- `FOS_PKI_REMOTE_CERTS` and `FOS_PKI_CRLS` are omitted because the initial PKI
  projection has no remote-certificate or generated-CRL category. They may be
  populated only after the typed API adds corresponding authorized artifacts.

For example, a node mounted at `/custom/pki` could receive:

```text
FOS_PKI_CA_CERTS=root:/custom/pki/authorities/effective/root/default/certificate.pem;issuing:/custom/pki/authorities/effective/issuing/default/certificate.pem
FOS_PKI_LOCAL_CERTS=tls:/custom/pki/issued/fgt/local/tls/private-key.pem:/custom/pki/issued/fgt/local/tls/certificate.pem
```

The translator omits an environment variable when its category is empty. It
preserves the projection's canonical order and applies any additional
vrnetlab-mandated ordering or deduplication deterministically. It emits paths
only, never file contents, passwords, or other secret values.

Before mutation, the injector treats all five names above as injector-owned,
including names whose categories are empty. If any exists in the effective
defaults or node environment, preparation fails and identifies the node,
variable, and source scope. It must not silently replace, merge, or reinterpret
a user-supplied value. Unrelated `FOS_*` variables, including those owned by
other plugins, are outside this collision check.

The injector also fails before the writer runs when:

- the context value or any nested value has the wrong API type;
- node names, kinds, classifications, fingerprints, or paths violate the API
  invariants;
- a projected guest path is not below the node's effective mount target;
- the corresponding authorized host file is absent, not a regular file, or
  escapes `staged_view`; or
- the topology node's PKI bind no longer matches the projection.

These checks validate the handoff, not certificate semantics. Because injector
preparation mutates only invocation-scoped topology state, it has no host work
to unwind in `prepare_failed()` or `after_call()`.

## Ordering and ownership

Ordering is declared in package metadata, never through a code-level
`plugin_dependencies` attribute:

```text
engulf_clab.lab_parser
        → engulf_clab.pki
        → engulf_clab.vrnetlab_fortigate_pki_injector
        → engulf_clab.lab_writer
```

The injector distribution depends on compatible releases of
`engulf-clab-pki-api`, `engulf-clab-pki`, the parser, and the writer. Its own
dependency entry-point group declares PKI before it and the writer after it.
For this integration, PKI adds only the API package; it does not depend on the
injector. PKI continues to declare parser-before and writer-after edges. Each
distribution tests its own entry-point declarations.

Ownership does not move across this boundary:

- PKI owns catalog interpretation, authorization, generation, views, binds,
  projections, provisioning journals, rollback, destroy cleanup, and PKI freeze
  contributions.
- The FortiGate injector owns only validation and mechanical translation of a
  typed node projection into the FortiGate launcher's environment contract.
- The topology writer owns serialization and rollback of the derived topology.
- The vrnetlab FortiGate launcher owns the exact `FOS_*` grammar, transfer into
  the VM, FortiOS CLI commands, object naming, installation, and launcher-side
  diagnostics.

PKI cleanup remains authoritative on every failure path. If PKI itself fails,
its existing callback-local `BaseException` handler removes attempt-created
views and material. If the injector or another later preparer fails, PKI's
`prepare_failed()` unwinds its completed preparation. The injector has no host
state to release and must not interfere with PKI's journal or leases.

## Freeze behavior

The injector runs only for deploy and changes only the derived topology. Freeze
operates on source declarations and PKI's existing freeze contribution; it does
not serialize injector-generated `FOS_*` variables. An ordinary archive may
contain `ECLAB_PKI_MANIFEST`, `ECLAB_PKI_MOUNT_TARGET`, and the PKI catalog as
required for reproducibility, but contains neither generated variables nor
generated private material.

The existing explicit encrypted-secret export remains the only path for private
identity material. The injector must not add a freeze contributor or sanitize
archives independently. Defrost recreates source declarations; a later deploy
rebuilds projections and injector output from the installed runtime contracts.

## Acceptance scenarios

Package-level and integration tests cover the following acceptance contract:

- Every eligible FortiGate node receives every node-selected trusted authority and
  intermediate without receiving any CA private key by default.
- A requested CA private key appears only in the projection and `FOS_*` input of
  the node that explicitly authorized it.
- Each issued leaf certificate, key, and chain appears only for its requesting
  node.
- Public CA paths use `FOS_PKI_CA_CERTS`, while authorized authority and leaf
  keypairs use `FOS_PKI_LOCAL_CERTS`; every entry has the mandatory leading
  refname field and exact category-specific field count.
- The initial injector omits `FOS_PKI_LOCAL_CERT_PASS_FILES`,
  `FOS_PKI_REMOTE_CERTS`, and `FOS_PKI_CRLS`; typed future artifacts populate
  them using the exact launcher grammar without certificate parsing.
- Self-signed roots, intermediates, cross-signed variants, shadowed explicit
  references, and duplicate fingerprints produce deterministic categories and
  order.
- The default target and per-node `ECLAB_PKI_MOUNT_TARGET` overrides produce
  matching binds and absolute `FOS_*` paths, and the control is absent from the
  derived environment.
- An injector-owned variable in topology defaults or node environment fails with
  an actionable collision diagnostic and is never overwritten.
- No PKI selector, no injector package, and non-`fortinet_fortigate` nodes leave
  topology environments unchanged.
- Installed metadata produces parser → PKI → injector → writer ordering.
- Missing files, escaped paths, mismatched binds, and malformed projection values
  fail before writer serialization.
- A later preparation failure unwinds PKI-created views and material without the
  injector attempting host cleanup.
- Ordinary freeze output contains source declarations but neither generated
  `FOS_*` variables nor private identity material.

Tests of the translator should use a fixture implementing the companion
vrnetlab contract and must not boot FortiOS, start TFTP, or run Containerlab.

## Out of scope

This integration does not own:

- changes to the canonical `FOS_*` launcher grammar or escaping rules;
- FortiOS CLI certificate installation, object naming, replacement, or cleanup
  beyond recording the launcher-owned effects above;
- TFTP or any other guest transfer implementation;
- changes to a FortiGate vrnetlab image or launcher;
- runtime certificate parsing by the injector; or
- injectors for other vendors or image families.

Those concerns require separate contracts and tests in the owning vrnetlab or
image-family integration projects.
