# Plugin Instructions

This directory contains the `engulf-clab-ensure-containerlab` plugin
distribution.

## Purpose

The plugin makes a `containerlab` executable available to normal wrapper calls.
It uses an executable `CONTAINERLAB_BIN`, a valid `CONTAINERLAB_DIR` checkout,
or an existing `containerlab` on `PATH`; otherwise it provisions a managed
checkout and builds `bin/containerlab` from it.

Managed checkout selection and safe staged clones belong in
`engulf-clab-ensure-checkout`. Keep Containerlab repository validation and Go
build details in this package. Plugin callbacks must use only `api.logger` for
diagnostics and must restore the process `PATH` after each call.

## Compatibility

- Goal catalog: `engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper`
- Application declaration: `engulf.plugins.v1.application.engulf_clab`
- Plugin ID: `engulf_clab.ensure_containerlab`

## Development Notes

- Derive from `SchemaBackedPlugin`. Keep provisioning flags in `PLUGIN_SCHEMA`,
  bind canonical `--eclab-containerlab-*` options to supported persistent
  `CONTAINERLAB_*` defaults, and read only normalized invocation/event
  environments so CLI precedence reaches source discovery and preparation.
- Apply only to calls whose wrapped binary is exactly `containerlab`. The
  read-only source selection published during `before_goal()` may inspect
  configured paths, `PATH`, and existing managed state. Keep provisioning, Git
  mutation, dependency probing, and Go builds in `prepare_call()`.
- Require Docker before resolution. Preserve explicit binary -> configured
  checkout -> `PATH` binary -> managed checkout order and invalid-value
  fallthrough.
- Validate checkouts with their tool-specific `go.mod` marker. Accept existing
  executable locations in the documented order and rebuild after a changed
  revision.
- Acquire the user-scoped repository lease before configured/managed update,
  clone, or build work. Use callback-bound logging through the logger adapter.
- Prepend only the resolved binary's parent to `PATH`, record the exact prior
  value, and restore it during `after_call()` even after a wrapped failure. Do
  not leak state between invocations on the plugin singleton.
- Never overwrite invalid managed state, reset dirty repositories, or mutate an
  explicit binary. Keep generic checkout mechanics in ensure-checkout.
- Keep dynamic help, `USAGE.md` resolution/update tables, defaults, and code
  synchronized.
- Run containerlab resolution/plugin tests plus ensure-checkout tests. Mock Git,
  Go, and dependency lookup; do not clone or build Containerlab in unit tests.
- Build/install the wheel and inspect active help/plugin discovery. Publish the
  selection hint before the terminal schema generator and replace it with the
  resolved checkout/binary source during preparation.
