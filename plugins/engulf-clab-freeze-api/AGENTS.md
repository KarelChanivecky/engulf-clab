# Agent instructions

Preserve the dependency-neutral protocol and deterministic entry-point discovery.
Do not add feature-specific fields to the API. Reject entry-point/name mismatches.

Contributor context state directories select the contributor's namespace, not
the calling freeze plugin. Keep that meaning documented and test the orchestrator
and PKI consumer together when state routing changes.

Keep image acquisition facts in the separate immutable image declarations,
not in contributor contexts. Discovery is read-only and missing inputs must be
representable. Share image manifest validation with consumers; do not import
Docker, eclab, or concrete providers here. Test every direct consumer of changes.

Keep runtime providers edition-neutral in the API: discover them through
`engulf_clab.freeze.runtime.v1`, reject mismatched entry-point names, and keep
tool commands and package provisioning inside the provider implementation.
