# Contributing

This package owns the local-file source provider for vrnetlab nodes. Keep path
selection and all its syntax here; keep source fetching in other providers and
build execution in `engulf-clab-vrnetlab-build`.

## Ownership and ordering

- The provider scans parser `EffectiveNode` snapshots, so values inherited from
  defaults, kinds, and groups are already resolved. Do not reimplement
  inheritance by reading raw YAML node maps.
- `engulf-clab-vrnetlab-build-api` owns the shared invocation context. Resolve
  each selected path to an absolute `Path`, then publish it with the API. The
  omitted node name means `default`; exact node sources take precedence over
  that fallback in the builder.
- The shared builder is a required plugin dependency and must run after every
  path provider. Declare the dependency and ordering in packaging, not in
  `plugin_dependencies` or a code-level ordering table.
- This plugin owns the user-visible `ECLAB_VRNETLAB_TYPE` and source controls,
  including completion, legacy aliases, build-job limit, dynamic help, and
  `PluginSchema`. Do not move these declarations into the builder.
- Preserve the source selector's exact argument removal so other wrapper
  plugins continue to receive the original command shape.

## Source behavior

Keep precedence as: exact CLI node selector, CLI `default`, node YAML path,
current `ECLAB_VRNETLAB_IMG_PATH`, then `ECLAB_VM_IMG` and `ECLAB_VM_SRC`.
Support `$VARIABLE` and `${VARIABLE}` path indirection, node/lab/global lookup,
and topology-directory relative paths. Reject duplicate selectors, unknown
nodes, and targets without a nonempty `ECLAB_VRNETLAB_TYPE`.
Nodes resolved through `default=PATH` must share one
`ECLAB_VRNETLAB_TYPE`; reject mixed types before preparation. Only publish an
API `default` source when every fallback user has the same builder type.

`analyze_call()` validates without writing the shared map or performing source
I/O beyond local topology/path inspection. `prepare_call()` repeats selection
from the immutable original arguments and publishes the resolved path set.
The shared map is invocation scoped and needs no explicit cleanup.

Completion reads only the selected local topology and filesystem entries. It
must not build images, inspect the vrnetlab checkout, touch persistent state, or
access the network. Keep the `default=` two-word option completion behavior.

Freeze image-source discovery stays read-only. Report source inputs and all
controls that enable a rebuild, but do not locate a checkout or run the shared
builder from the freeze hook.

## Documentation and validation

Keep `PLUGIN_SCHEMA`, concise dynamic help, exact `USAGE.md` syntax, package
metadata ordering, and `AGENTS.md` aligned. Preserve the fixed `ECLAB` prefix
across eclab editions and keep host paths out of committed examples. When the
source-resolution contract changes, update direct consumers such as freeze
discovery and the shared builder's context reader.
