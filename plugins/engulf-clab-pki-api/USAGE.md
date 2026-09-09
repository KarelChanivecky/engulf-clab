# PKI projection API

Install this package with a PKI producer and any image-family injector. Producers
publish one projection-v2 `PkiNodeProjections` value under
`PKI_NODE_PROJECTIONS_CONTEXT` after
authorized node views have been staged. Consumers may translate those paths but
must not infer or expand authorization.

Each `ProjectedFile` pairs an absolute host path below a node's staged view with
the corresponding absolute POSIX path below its in-container mount target.
Authority projections carry canonical `global/name[/variant]` identity,
SHA-256 fingerprint, and trust classification. `public_authorities` is the
available public catalog; `trusted_authorities` is the node-selected trust set.
Requested authorities are explicit private identities, and issued identities
use canonical certificate declaration IDs and remain visible only to their
requesting node.

Projection node names preserve valid Containerlab names, including namespaced
bridge spellings such as `client-net|segments`. They remain a single path-safe
component: empty names, `.`/`..`, path separators, path-list delimiters, NUL,
and control characters are rejected.

The package performs structural validation only. It does not parse catalogs or
certificates, access files, mutate topologies, import Engulf, or define a guest
installation protocol.
