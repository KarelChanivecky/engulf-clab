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

Plugin code imports `engulf_api`, not `engulf`.
It derives from `ExecutableWrapperPlugin` supplied by
`engulf_executable_wrapper_api`.

## Development Notes

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
- `StateStore.path()` is used for the checkout directory because Git requires
  a filesystem path. Direct checkout operations therefore bypass managed-file
  atomic writes; clone into a temporary sibling and rename only after validating
  it.
- Do not update, reset, clean, or otherwise mutate an existing valid checkout.
  Users control external checkouts and can remove the managed checkout when they
  explicitly want it recloned.
- Keep validation vendor-neutral. Requested `vendor/type` builders are validated
  by the build plugin.
- Do not perform real network clones in automated tests. Mock Git and create
  temporary checkout markers.
- Keep runtime help, README opt-in/resolution/update behavior, context IDs, and
  dependency lists synchronized.
- Run topology, checkout, plugin, and build-pipeline tests plus
  ensure-checkout tests. Mock Docker/QEMU/Git lookup and never build vendor
  images in unit tests.
- Build/install the wheel and verify active help/discovery with the downstream
  builder installed. Regenerate both ensure-vrnetlab skill references after
  behavior or documentation changes.
