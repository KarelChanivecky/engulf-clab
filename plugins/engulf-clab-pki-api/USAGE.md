# PKI projection API

Install this package with a PKI producer and any image-family injector. Producers
publish one `PkiNodeProjections` value under `PKI_NODE_PROJECTIONS_CONTEXT` after
authorized node views have been staged. Consumers may translate those paths but
must not infer or expand authorization.

Each `ProjectedFile` pairs an absolute host path below a node's staged view with
the corresponding absolute POSIX path below its in-container mount target.
Authority projections carry resolved identity, SHA-256 fingerprint, and trust
classification. Requested authorities expose a private key only when the node
request authorized it; issued identities are visible only to their requesting
node.

The package performs structural validation only. It does not parse catalogs or
certificates, access files, mutate topologies, import Engulf, or define a guest
installation protocol.
