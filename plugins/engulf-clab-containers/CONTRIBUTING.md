# Container Manager Plugin Instructions

This is the only plugin that turns declarative container collections into
topology mutations. Keep collection discovery under normal Engulf activation,
accept only typed fields from `engulf-clab-containers-api`, and never mutate the
source topology. It must run after collections and the lab parser, and before
the image dispatcher and lab writer.

- Derive from `SchemaBackedPlugin` so discovery controls and advertised values
  participate in completion without parsing generated schema artifacts.
- Keep plugin ID `engulf_clab.containers`, collection context
  `engulf_clab.containers.collections`, and topology context declarations stable.
- Validate the complete catalog and proposed merge during `analyze_call()`;
  perform only deferred editor operations during `prepare_call()`.
- Declare parser, image dispatcher, writer, and schema dependencies only in the
  package entry-point metadata. Do not restore code-level `plugin_dependencies`.
- `prepare_call()` records only invocation-local editor operations and acquires no
  external resource, so this plugin needs no `prepare_failed()` override.
- Do not inject package build paths into node environment. Generic custom build
  parameters are valid fixed-prefix node `env` controls owned by the image
  dispatcher; runtime recipe defaults remain collection-owned.
- Preserve canonical `:latest` naming, namespace collision detection, package
  asset validation, required management networking, and conflict-safe merge
  rules. Do not silently override user fields or fall through malformed managed
  names to a registry pull.
- Keep user documentation explicit that source topologies declare the recipe
  kind. Injection runs for deploy and single-source redeploy, while other
  Containerlab commands parse the raw topology.
- The manager must not run Docker, import collection implementation modules
  directly, inspect undeclared fields, or retain state. Register a pure image
  provider; the image dispatcher owns builds and the writer owns cleanup.
- Keep `--eclab-containers-help` side-effect free and based only on active
  registered collections. Update runtime help and `USAGE.md` together when catalog
  syntax changes.
- Run manager tests, container API tests, and at least one installed core
  collection discovery/help check. Package-data behavior must be tested from a
  built wheel when paths or assets change.
- Record `PLUGIN_SCHEMA` during `before_goal`; the schema dependency must remain
  last and reference snapshots come from built package data. Run `make check-skill`.

## Validation

Run the narrowest checks that exercise the changed boundary:

```bash
.venv/bin/python -m compileall -q plugins/engulf-clab-containers/src
.venv/bin/python -m pytest -q plugins/engulf-clab-containers/tests
make check-skill
```

Container API changes require both the manager suite here and the
`engulf-clab-containers-core` collection suite.

Run `make build-<package>` for a distribution build (or `make build` for
every distribution), and `git diff --check` before committing. Never run
real deploy/destroy, Docker builds, Git clones, or
privileged MCP installation as part of validation.
