# Plugin Instructions

This directory contains the `engulf-clab-ensure-vrnetlab` plugin distribution.

## Purpose

The plugin prepares a vendor-neutral vrnetlab checkout before the build plugin
runs. It publishes the resolved checkout through Engulf call context and does
not build vendor images itself.

## Compatibility

- Goal catalog: `engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper`
- Application declaration: `engulf.plugins.v1.application.engulf_clab`
- Plugin import package: `engulf_clab_ensure_vrnetlab`
- Plugin ID: `engulf_clab.ensure_vrnetlab`
- Published context ID: `engulf_clab.vrnetlab.path`

Plugin code imports `engulf_api`, not `engulf`. It derives from
`SchemaBackedPlugin`, which remains an executable-wrapper plugin adapter.

## Development Notes

- Canonical `--eclab-vrnetlab-*` controls bind supported persistent
  `VRNETLAB_*` defaults in `PLUGIN_SCHEMA`. Read only normalized invocation/event
  environments so CLI precedence reaches source hints and preparation.
- Use the fixed `ECLAB` environment prefix (`contract.LABEL_PREFIX`). Do not
  derive it from `api.application.short_product_name`/`product` — labels must
  stay portable across editions. Analyze `deploy` calls without side effects,
  then provision only during `prepare_call()` once every analyzer has accepted
  the invocation. The plugin still activates only when the topology contains a
  node with a nonempty `ECLAB_VRNETLAB_TYPE` environment value.
- A valid `VRNETLAB_DIR` takes precedence. Invalid configured paths are warned
  about and ignored before the managed fallback is considered.
- The managed fallback belongs under `api.state(StateScope.USER)` because one
  checkout is shared by image builds for every workspace.
- Publish a read-only source selection during `before_goal()` so strict schema
  generation can preempt the wrapped call. Publish the resolved checkout during
  `prepare_call()` alongside `engulf_clab.vrnetlab.path`; do not clone or update
  merely to produce the early hint. Failed goals acknowledge an early hint in
  `after_goal()` when preprocessing stopped before the terminal generator.
- Declare the hard parser/schema dependencies and their preprocessing order in
  distribution entry-point metadata. Do not declare plugin dependencies in code.
- A prepared checkout and its update metadata are durable user-scoped cache, while
  published contexts are invocation-scoped. Do not remove either in
  `prepare_failed()` when a later plugin fails; this plugin retains no transient or
  process-global resource that needs preparation unwind.
- `StateStore.path()` is used for the checkout directory because Git requires
  a filesystem path. Direct checkout operations therefore bypass managed-file
  atomic writes; clone into a temporary sibling and rename only after validating
  it.
- Mutate an existing clean Git checkout only for an explicit update/version
  request. Reject dirty worktrees, leave non-Git checkouts unchanged, and never
  reset, clean, or repair a checkout. Users may remove a managed checkout when
  they intentionally want it recloned.
- Keep validation vendor-neutral. Requested `vendor/type` builders are validated
  by the build plugin.
- Do not perform real network clones in automated tests. Mock Git and create
  temporary checkout markers.
- Keep runtime help, `USAGE.md` opt-in/resolution/update behavior, context IDs, and
  dependency lists synchronized.
- Run topology, checkout, plugin, and build-pipeline tests plus
  ensure-checkout tests. Mock Docker/QEMU/Git lookup and never build vendor
  images in unit tests.
- Build/install the wheel and verify active help/discovery with the downstream
  builder installed. Keep `PLUGIN_SCHEMA` and its last-running generator
  dependency aligned with checkout and opt-in controls.
