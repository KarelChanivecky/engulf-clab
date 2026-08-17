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

- Apply only to calls whose wrapped binary is exactly `containerlab`. Keep all
  probing, provisioning, Git work, and Go builds in `prepare_call()`.
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
- Keep dynamic help, README resolution/update tables, defaults, and code
  synchronized.
- Run containerlab resolution/plugin tests plus ensure-checkout tests. Mock Git,
  Go, and dependency lookup; do not clone or build Containerlab in unit tests.
- Build/install the wheel and inspect active help/plugin discovery. Regenerate
  the skill's ensure-containerlab references after changes.
