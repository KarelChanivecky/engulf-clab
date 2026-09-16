# Plugin Instructions

This directory contains the `engulf-clab-dockerfile-build` plugin distribution.

## Purpose

The plugin converts node Dockerfile controls into a neutral image graph
fragment before `engulf-clab deploy` or single-source `redeploy`. The shared resolver and dispatcher own
provider recursion and Docker execution.

## Compatibility

- Goal catalog: `engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper`
- Application declaration: `engulf.plugins.v1.application.engulf_clab`
- Dependency declaration: `engulf.plugins.v1.dependency.engulf_clab_dockerfile_build`
- Plugin ID: `engulf_clab.dockerfile_build`

Declare the lab-parser, image-build, and schema ordering edges only in the
package entry-point metadata. Do not restore `plugin_dependencies` on the
plugin class; Engulf rejects code-declared dependencies.

Use the fixed `ECLAB` prefix (`config.LABEL_PREFIX`). Do not derive it from
`api.application.short_product_name`/`product` — labels must stay portable
across editions.
Read `TopologySession.materialize()` during preparation so earlier topology
mutators can affect declarations, then append only immutable graph values.

- Derive from `SchemaBackedPlugin`. Node Docker fields remain topology `env`
  values and must never be consumed as wrapper options. Concurrency controls
  belong to `engulf_clab.image_build`.
- Keep analysis limited to parsing, path/type validation, conflict prediction,
  and an immutable contribution. Never invoke or probe Docker from analysis or
  help.
- Preserve the reserved `--file`/`--tag` checks across short, long, attached,
  and equals forms before constructing a `DockerfileRecipe`.
- Resolve relative paths from the topology directory and validate file/directory
  roles. Do not require the Dockerfile to be inside the context for ordinary
  user declarations; Docker decides whether the selected combination is valid.
- Accept source image expressions after the shared parser eagerly expands them
  from the effective call environment. Reject only an image tag still containing
  variable syntax after expansion, because every built output tag must be literal.
- Parse `ECLAB_DOCKER_BASE_NODE` as a string-encoded boolean. A marked node
  remains an explicit graph root; record its recipe before deleting it from the
  mutable deploy topology.
- Never mutate the source YAML or delete an unmarked node. The writer alone
  serializes the derived topology after this plugin's deletion operation.
- Let `engulf-docker-image-core` coalesce definitions, inspect `FROM`, select
  providers, acquire leases, schedule workers, and aggregate failures. Do not
  duplicate that policy in this adapter.
- Preparation changes only invocation-scoped topology and image-graph context.
  It acquires no external resource, so it needs no `prepare_failed` cleanup.
- Do not delete built images on destroy. Docker caching and tag lifecycle are
  outside this plugin's cleanup responsibility.
- Keep dynamic help, `USAGE.md` fields, prefix derivation, parser validation,
  and graph conversion synchronized.
- Run config, build, and plugin tests; include parser/manager/core tests when
  changing materialized-topology behavior. Mock Docker in automated tests.
- Keep `PLUGIN_SCHEMA` aligned with every node variable and retain the
  last-running schema dependency. Run `make check-skill` after changes.

## Validation

Run the narrowest checks that exercise the changed boundary:

```bash
.venv/bin/python -m compileall -q plugins/engulf-clab-dockerfile-build/src
.venv/bin/python -m pytest -q plugins/engulf-clab-dockerfile-build/tests
make check-skill
```

Run `make build-<package>` for a distribution build (or `make build` for
every distribution), and `git diff --check` before committing. Never run
real deploy/destroy, Docker builds, Git clones, or
privileged MCP installation as part of validation.
