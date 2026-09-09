# Contributing

Keep this package independent of Engulf, PKI implementations, topology parsers,
and image families. Public values are frozen and slotted; collection fields are
tuples. Validate lexical authorization boundaries at construction time, but
leave filesystem availability checks to invocation-time consumers.

The context ID, enum values, field meanings, and host/container correspondence
are stable public API. Add a new optional artifact category instead of weakening
an existing field. Never put certificate bytes, key bytes, passwords, catalog
objects, or mutable topology objects in a projection.

Do not apply the narrower PKI catalog-name grammar to `node_name`. Containerlab
names such as `client-net|segments` must round-trip, while values that could
escape a single staged-view path component remain invalid.
