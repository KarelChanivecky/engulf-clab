# Plugin Instructions

This directory contains the `engulf-clab-vrnetlab-build` plugin distribution.

## Purpose

The plugin finds nodes with `ECLAB_VRNETLAB_TYPE` in their Containerlab
node environment and ensures their Docker images are built before deploy or single-source redeploy.
The builder is selected by the vendor/type path beneath a prepared vrnetlab
checkout.

## Compatibility

- Goal catalog: `engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper`
- Application declaration: `engulf.plugins.v1.application.engulf_clab`
- Docker-image goal adapter: `engulf.plugins.v1.goal.v1.org_engulf_docker_image`
  (`org.engulf.docker.vrnetlab-build`)
- Plugin import package: `engulf_clab_vrnetlab_build`
- Executable-wrapper plugin ID: `engulf_clab.vrnetlab_build`
- Docker-image adapter and provider ID: `org.engulf.docker.vrnetlab-build`
- Prepared-checkout context ID: `engulf_clab.vrnetlab.path`
- Required producer plugin ID: `engulf_clab.ensure_vrnetlab`

Plugin code imports `engulf_api`, not `engulf`. It derives from
`SchemaBackedPlugin`, which remains an executable-wrapper plugin adapter.
Keep these adapters separate: each entry-point name must equal that adapter's
`plugin_id`. Wrapper ordering belongs in the package metadata dependency group,
not on the Python class.

## Development Notes

- Keep the concurrency flag bound to its persistent runtime default and read
  the normalized event environment. The repeatable image-source flag is a
  plugin-owned `NODE=PATH` option: analyze it without side effects, remove its
  exact argument indexes, and re-parse the immutable original arguments during
  preparation. Node `ECLAB_VRNETLAB_TYPE` and topology image-source values
  remain node `env` controls. `topology_nodes()` exposes parser `EffectiveNode`
  data; do not reintroduce raw node reads or local inheritance logic.
- Require image selectors to follow a deploy or single-source redeploy command. Other topology-aware
  plugins receive the same original argument tuple, so treating this option as
  a pre-command global would bypass their command detection.
- Treat `default` as the reserved CLI fallback selector. Preserve exact-selector
  precedence over node YAML, followed by `default`, the persistent environment
  fallback, and legacy aliases. Reject duplicate selectors, unknown nodes, and
  nodes that do not opt into vrnetlab construction.
- Keep image completion bounded to parsing the selected local topology and
  listing its opted-in node names and local paths. It must not build images,
  discover repositories, touch state, or access the network. Relative path
  candidates use the topology directory, matching runtime resolution.
- Keep the plugin vendor-neutral. Builder-specific behavior belongs in the
  selected vrnetlab `vendor/type` directory, not in Python conditionals.
- Use the fixed `ECLAB` prefix (`engulf_clab_ensure_vrnetlab.LABEL_PREFIX`).
  Do not derive it from `api.application.short_product_name`/`product` —
  labels must stay portable across editions.
- Preserve the source qcow2 basename because vrnetlab Makefiles commonly
  derive the native Docker tag from it.
- Never extract an archive wholesale. Stream its one qcow2 member into a
  temporary directory so archive paths cannot escape the extraction root.
- Existing builder qcow2 files and Docker-context artifacts must be restored
  or cleaned in `finally` paths.
- Parallelize across builder directories only. Images using the same builder
  directory must remain serial because builds temporarily modify that directory.
- Acquire the complete image/builder lease set in the callback thread before
  launching workers. Invocation API lease contexts and state transactions must
  not overlap across threads; perform fingerprint state operations serially.
- Build fingerprints belong in `api.state(StateScope.USER)` because Docker
  tags are shared across workspaces. Use Engulf's managed `exists`,
  `read_text`, and `write_text` operations rather than direct filesystem I/O.
- Require lab-unique requested image tags in help and authoring guidance. This
  is firm guidance rather than runtime validation: image leases prevent
  simultaneous mutation, but shared tags still couple independently launched
  labs to one host-global Docker image identity.
- State handles are invocation-bound. Obtain and consume the store inside the
  active callback and never retain it on the plugin instance. Keep validation in
  side-effect-free `analyze_call()` and image work in `prepare_call()`.
- Treat the shared provider's refreshed request map as invocation state. Clear it
  after every attempted call, when a later preparer fails, and from this plugin's
  own preparation exception paths; Engulf does not call `prepare_failed` on the
  preparer that raised.
- Do not discover or clone vrnetlab here. The hard ensure-vrnetlab dependency
  owns `VRNETLAB_DIR`, managed provisioning, and context publication. Keep the
  dependency edge and consume only the published context path.
- Do not run real Docker builds in automated tests. Mock Docker and Make and
  use temporary builder directories.
- Keep custom argument registration, `PLUGIN_SCHEMA`, dynamic help, `USAGE.md`
  selector precedence/formats, prefix derivation, fingerprint components,
  native/requested tag behavior, and cleanup guarantees synchronized.
- Run option/completion, config, source, image, state/vrnetlab, and plugin tests plus the
  ensure-vrnetlab build-pipeline suite. Build/install both wheels and verify
  discovery ordering/context wiring.
- Keep `PLUGIN_SCHEMA` aligned with image-source aliases, opt-in variables, and
  the last-running generator dependency; run `make check-skill`.

## Validation

Run the narrowest checks that exercise the changed boundary:

```bash
.venv/bin/python -m compileall -q plugins/engulf-clab-vrnetlab-build/src
.venv/bin/python -m pytest -q plugins/engulf-clab-vrnetlab-build/tests
make check-skill
```

Also run the `engulf-clab-ensure-vrnetlab` suite when checkout handling changes.

Run `make build-<package>` for a distribution build (or `make build` for
every distribution), and `git diff --check` before committing. Never run
real deploy/destroy, Docker builds, Git clones, or
privileged MCP installation as part of validation.
