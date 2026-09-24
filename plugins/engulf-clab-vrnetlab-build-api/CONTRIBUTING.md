# Contributing

This package owns only the provider to builder boundary. Keep source selection,
CLI registration, environment names, topology conventions, and build execution
in their respective provider or builder packages.

`VRNETLAB_BUILD_CONTEXT` is a shared Engulf invocation context. Providers must
obtain it with `get_build_context(api, create=True)`, then construct a
`VrnetlabBuildAPI` bound to that context. Providers and the builder use this
object for all reads and writes. Each source key, including `default`, can be
set once by default. `set_image_source(..., override=True)` deliberately
replaces the existing value for that key; callers must use it only when their
documented source precedence authorizes that replacement. `source_for(node)`
applies exact-node then default fallback, and `sources()` returns an immutable
snapshot. `unprovisioned_nodes(names)` filters caller-supplied candidate names
using the same exact-node/default coverage rule. It reports missing source
declarations, not Docker build status. `uses_default_source(node)` reports
whether lookup falls through to the default key and lets the builder validate
the common builder-type invariant.

The context is mutable because independent provider callbacks contribute paths
in order. Protect every mutation and snapshot with the context lock. Do not
store callbacks, `InvocationAPI`, logger, state-store, or other invocation-bound
objects inside it. Keep values transportable: absolute `Path` values, node
names, and a positive integer job count only.

Do not import `engulf`; this public API depends only on `engulf-api`. Keep
context IDs globally unique and stable across releases. Providers should
declare the builder plugin as a packaging dependency and order themselves ahead
of it in preprocessing so all paths are present before it runs.
