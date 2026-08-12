# Plugin Instructions

This directory contains the `engulf-clab-vrnetlab-build` plugin distribution.

## Purpose

The plugin finds nodes with `<PREFIX>_VRNETLAB_TYPE` in their Containerlab
node environment and ensures their Docker images are built before deploy.
The builder is selected by the vendor/type path beneath a prepared vrnetlab
checkout.

## Compatibility

- Goal catalog: `engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper`
- Application declaration: `engulf.plugins.v1.application.engulf_clab`
- Plugin import package: `engulf_clab_vrnetlab_build`
- Plugin ID: `engulf_clab.vrnetlab_build`
- Prepared-checkout context ID: `engulf_clab.vrnetlab.path`
- Required producer plugin ID: `engulf_clab.ensure_vrnetlab`

Plugin code imports `engulf_api`, not `engulf`.
It derives from `ExecutableWrapperPlugin` supplied by
`engulf_executable_wrapper_api`.

## Development Notes

- Keep the plugin vendor-neutral. Builder-specific behavior belongs in the
  selected vrnetlab `vendor/type` directory, not in Python conditionals.
- Derive `<PREFIX>` from callback-bound `api.application.short_product_name`,
  falling back to `api.application.product`. The official application uses
  `ECLAB`; a normalized edition short product name selects another prefix
  without changing the shared application identity.
- Preserve the source qcow2 basename because vrnetlab Makefiles commonly
  derive the native Docker tag from it.
- Never extract an archive wholesale. Stream its one qcow2 member into a
  temporary directory so archive paths cannot escape the extraction root.
- Existing builder qcow2 files and Docker-context artifacts must be restored
  or cleaned in `finally` paths.
- Build fingerprints belong in `api.state(StateScope.USER)` because Docker
  tags are shared across workspaces. Use Engulf's managed `exists`,
  `read_text`, and `write_text` operations rather than direct filesystem I/O.
- State handles are invocation-bound. Obtain and consume the store inside the
  active callback and never retain it on the plugin instance. Keep validation in
  side-effect-free `analyze_call()` and image work in `prepare_call()`.
- Do not discover or clone vrnetlab here. The hard ensure-vrnetlab dependency
  owns `VRNETLAB_DIR`, managed provisioning, and context publication. Keep the
  dependency edge and consume only the published context path.
- Do not run real Docker builds in automated tests. Mock Docker and Make and
  use temporary builder directories.
