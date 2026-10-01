# License-pool metadata API contributor guidance

This package owns only the framework-neutral contract for pool metadata. The
collector in `engulf-clab-license-pool` owns interactive input, pool registry
state, resource leases, and publishing `.lic-pool` changes.

Contributors publish one object in
`engulf_clab.license_pool.metadata.v1`; the entry-point name must equal its
stable, globally unique `contributor_id`. `collect_metadata()` receives the
canonical pool path, selected Containerlab kind, original command arguments,
normalized environment, that contributor's current namespace, legacy flat
metadata, and whether this is an update or an interactive invocation.

Return a mapping containing only additional changed fields, or `None` when
nothing should change. Omitted fields are preserved. A field set to `None` is
removed from the contributor namespace. Declare simple metadata fields with
`metadata_variables` and `LicensePoolVariable`; the collector owns their
validation, CLI overrides, prompting, defaults, and persistence. Use
`context.variable_values` for read-only answers when deriving other metadata.
An optional `resolve_variable_values(context)` method can provide typed values
from contributor-specific flags or environment values. Generic CLI overrides
are present in the context passed to this method and take precedence over its
return value. Return only declared variable names and values matching their
declared types.
Set `optional=True` when a value may be omitted; without a default the
collector skips it on noninteractive calls and accepts an empty interactive
answer. A declared default still supplies an omitted value.
Do not write `.lic-pool` or perform registry operations in a contributor.
Metadata must be JSON-compatible and must not contain license contents,
secrets, or local license paths.

The API reads legacy flat `.lic-pool` objects as `legacy` and writes the
versioned namespaced form only when the collector has a contribution to save.
When touching this contract, update both direct consumer docs and their package
dependency floors. Run the focused API and collector checks when requested.
