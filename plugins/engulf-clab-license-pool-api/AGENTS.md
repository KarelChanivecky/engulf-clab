# License-pool metadata API instructions

Keep this package independent of Engulf, Containerlab, and vendor editions.
It defines the contributor contract and the shared `.lic-pool` document format;
the `engulf-clab-license-pool` plugin owns prompts, leases, registration, and
atomic writes.

Discover contributors deterministically from
`engulf_clab.license_pool.metadata.v1`, and reject entry-point names that do not
match `contributor_id`. Optional `metadata_variables` declarations use the
typed `LicensePoolVariable` contract; the collector validates and prompts for
them. An optional `resolve_variable_values(context)` method supplies typed
contributor-specific values after generic CLI overrides and before stored
values, prompts, or defaults. Optional variables without defaults may be
omitted. Contributors return only additional owned metadata fields. Omitted
keys preserve stored values; a `None` value removes an owned key. Never let a
contributor write the shared manifest directly.

Keep legacy flat manifests readable. Do not put secrets, license contents, or
license paths in metadata. Use the package's own docs for the public contract.
