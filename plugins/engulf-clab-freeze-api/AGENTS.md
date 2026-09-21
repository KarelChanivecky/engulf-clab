# Agent instructions

Preserve the dependency-neutral protocol and deterministic entry-point discovery.
Do not add feature-specific fields to the API. Reject entry-point/name mismatches.

Keep image acquisition facts in the separate immutable image declarations,
not in contributor contexts. Discovery is read-only and missing inputs must be
representable. Share image manifest validation with consumers; do not import
Docker, eclab, or concrete providers here. Test every direct consumer of changes.
