# Plugin Instructions

This directory contains the `engulf-clab-dockerfile-build` plugin distribution.

## Purpose

The plugin builds a node's declared Docker image from a Dockerfile before
`engulf-clab deploy`. A node without a Dockerfile declaration may reuse an
image tag built for another node.

## Compatibility

- Goal catalog: `engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper`
- Application declaration: `engulf.plugins.v1.application.engulf_clab`
- Plugin ID: `engulf_clab.dockerfile_build`

Use the fixed `ECLAB` prefix (`config.LABEL_PREFIX`). Do not derive it from
`api.application.short_product_name`/`product` — labels must stay portable
across editions.
The plugin runs `docker build` during `prepare_call()` only and must never build
during analysis. Acquire one multi-lease context covering every image tag before
launching parallel workers; callback-bound API lease contexts must not overlap.
Read `TopologySession.materialize()` during preparation so earlier topology
injectors can contribute packaged Dockerfile recipes.

- Derive from `SchemaBackedPlugin`. Keep
  `--eclab-docker-build-jobs` bound to its persistent runtime default and read
  the normalized event environment. Node Docker fields remain topology `env`
  values and must never be consumed as wrapper options.
- Keep analysis limited to parsing, path/type validation, conflict prediction,
  and an immutable contribution. Never invoke or probe Docker from analysis or
  help.
- Build with an argv, not a shell. Preserve the reserved `--file`/`--tag` checks
  across short, long, attached, and equals forms.
- Resolve relative paths from the topology directory and validate file/directory
  roles. Do not require the Dockerfile to be inside the context for ordinary
  user declarations; Docker decides whether the selected combination is valid.
- Reject Containerlab variable syntax in a configured image tag during
  analysis. The builder consumes raw topology values before Containerlab's
  variable expansion, so every built tag must be literal.
- Coalesce identical definitions by image tag and reject conflicting ones.
  Acquire the complete multi-image lease set in the callback thread before
  launching workers; never use invocation-bound API objects inside workers.
- Let all worker futures settle and combine deterministic failures. Preserve
  Docker's output and do not configure logging or print operational messages.
- Do not delete built images on destroy. Docker caching and tag lifecycle are
  outside this plugin's cleanup responsibility.
- Keep dynamic help, README fields, prefix derivation, parser validation, and
  constructed Docker argv synchronized.
- Run config, build, and plugin tests; include parser/manager/core tests when
  changing materialized-topology behavior. Mock Docker in automated tests.
- Keep `PLUGIN_SCHEMA` aligned with every node/runtime variable and retain the
  last-running schema dependency. Run `make check-skill` after changes.
