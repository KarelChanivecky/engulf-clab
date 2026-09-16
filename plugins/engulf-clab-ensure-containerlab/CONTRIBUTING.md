# Plugin Instructions

This directory contains the `engulf-clab-ensure-containerlab` plugin
distribution.

## Purpose

The plugin makes a `containerlab` executable available to normal wrapper calls.
It uses an executable `CONTAINERLAB_BIN`, a valid `CONTAINERLAB_DIR` checkout,
or an existing `containerlab` on `PATH`; otherwise it provisions a managed
checkout and builds `bin/containerlab` from it, stamping version provenance
into the binary so `containerlab version` identifies the build.

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
- Stamp version provenance into the managed build. Read the module path from
  `go.mod` rather than hardcoding it, and pass `-ldflags` setting `cmd.Version`
  (from `git describe --tags`), `cmd.commit`, and `cmd.date`. A plain `go build`
  leaves the binary reporting 0.0.0 / none / unknown, which hides how far a fork
  has drifted from upstream and makes it unidentifiable in a bug report.
  Provenance is best effort: never fail a build because git is unavailable.
- Apply only to calls whose wrapped binary is exactly `containerlab`. The
  read-only source selection published during `before_goal()` may inspect
  configured paths, `PATH`, and existing managed state. Keep provisioning, Git
  mutation, dependency probing, and Go builds in `prepare_call()`. The
  preempting `sudoless` maintenance command is the sole exception: it resolves
  the binary and completes its explicitly requested host setup in
  `before_goal()` without entering the wrapped-call lifecycle.
- Require Docker before resolution. Preserve explicit binary -> configured
  checkout -> `PATH` binary -> managed checkout order and invalid-value
  fallthrough.
- Validate checkouts with their tool-specific `go.mod` marker. Accept existing
  executable locations in the documented order and rebuild after a changed
  revision.
- Acquire the user-scoped repository lease before configured/managed update,
  clone, or build work. Use callback-bound logging through the logger adapter.
- Prepend only the resolved binary's parent to `PATH`, record the exact prior
  value, and restore it during `after_call()` even after a wrapped failure or
  during `prepare_failed()` when a later preparer raises. Do not leak state
  between invocations on the plugin singleton.
- Keep the schema-plugin dependency in the package's dependency entry-point
  metadata; runtime code must not declare `plugin_dependencies`.
- Never overwrite invalid managed state, reset dirty repositories, or mutate an
  explicit binary during normal resolution. The explicit `sudoless` command may
  root-own and set mode `4755` on the resolved binary. It must create/authorize
  both `clab_admins` and `docker` before enabling SUID, reject root callers, and
  never use a shell.
- Keep dynamic help, `USAGE.md` resolution/update tables, defaults, and code
  synchronized.
- Run containerlab resolution/plugin tests plus ensure-checkout tests. Mock Git,
  Go, and dependency lookup; do not clone or build Containerlab in unit tests.
- Build/install the wheel and inspect active help/plugin discovery. Publish the
  selection hint before the terminal schema generator and replace it with the
  resolved checkout/binary source during preparation. Do not publish a source
  from a command that preempts the generator. If an entered later plugin fails
  before the generator, acknowledge this plugin's hint during `after_goal()` so
  the primary error is not followed by an unused-context warning.

## Validation

Run the narrowest checks that exercise the changed boundary:

```bash
.venv/bin/python -m compileall -q plugins/engulf-clab-ensure-containerlab/src
.venv/bin/python -m pytest -q plugins/engulf-clab-ensure-containerlab/tests
make check-skill
```

Checkout-helper changes require both ensure-plugin suites
(`engulf-clab-ensure-containerlab` and `engulf-clab-ensure-vrnetlab`).

Run `make build-<package>` for a distribution build (or `make build` for
every distribution), and `git diff --check` before committing. Never run
real deploy/destroy, Docker builds, Git clones, or
privileged MCP installation as part of validation.
