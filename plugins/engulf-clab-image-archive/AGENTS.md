# Plugin Instructions

This directory contains the `engulf-clab-image-archive` plugin distribution.

## Purpose

The plugin turns a node's archive declaration into a Docker image provider that
offers a `DockerArchiveRecipe` for that node's image tag. The shared resolver
and dispatcher own provider selection, leases, and Docker execution; loading and
retagging happen in `engulf-docker-image-core`, not here.

## Compatibility

- Goal catalog: `engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper`
- Application declaration: `engulf.plugins.v1.application.engulf_clab`
- Docker image goal catalog: `engulf.plugins.v1.goal.v1.org_engulf_docker_image`
- Dependency declaration: `engulf.plugins.v1.dependency.engulf_clab_image_archive`
- Plugin ID: `engulf_clab.image_archive`
- Provider ID: `org.engulf.docker.image-archive`

Declare the lab-parser, image-build, and schema ordering edges only in package
entry-point metadata. Do not restore `plugin_dependencies` on the plugin class;
Engulf rejects code-declared dependencies.

Use the fixed `ECLAB` prefix (`config.LABEL_PREFIX`). Do not derive it from
`api.application.short_product_name`/`product` — labels must stay portable
across editions.

- Derive from `SchemaBackedPlugin`. Archive fields remain topology `env` values
  and must never be consumed as wrapper options.
- Keep `analyze_call` limited to parsing and path/type validation returning an
  immutable contribution. Never invoke or probe Docker from analysis or help.
- Read `TopologySession.materialize()` during preparation so earlier topology
  mutators affect declarations, and so the recorded tags match the roots
  `engulf_clab.image_build` derives from the same document.
- Read inherited image/env fields through parser EffectiveNode snapshots;
  never duplicate defaults/kind/group merging or discard declaration origins.
- Keep `provide()` a pure, lock-guarded lookup. It runs on resolver worker
  threads with no invocation api; all filesystem work belongs to
  `refresh_requests` and analysis.
- Publish one provider instance under both the wrapper plugin and the
  `image_plugin` adapter so either dispatch path answers for the same requests.
- Treat the refreshed provider map as invocation-scoped prepared state. Clear it
  after an attempted call, during `prepare_failed()` when a later preparer
  raises, and inside `prepare_call()` if that callback fails after refreshing it.
- Offer at `PREFERRED` authority with `fallback_on_failure=False`: an explicitly
  selected archive is the node's declared image source, and a registry pull of
  the same tag would be a different image.
- Reject canonical image-tag collisions during preparation unless the requests
  have the same archive path and SHA-256, source reference, and reload policy;
  diagnostics must name both nodes.
- Default to `only_if_missing=True` and let `ECLAB_IMAGE_ARCHIVE_RELOAD` opt into
  loading on every deploy. Manifest recipes always reload to restore recorded content.
- Validate image manifests through freeze-api before populating the provider;
  their dependency-only images participate in ordinary recursive resolution.
  Keep `freeze.py` discovery read-only and allow missing paths there, while
  deploy analysis continues to require usable files.
- Never choose a member of a multi-image archive implicitly; require
  `ECLAB_IMAGE_ARCHIVE_REF` when the archive does not carry the node image.
- Do not extract, inspect, or rewrite archive contents in this plugin; `docker
  load` owns the format.
- Do not delete loaded images on destroy. Docker tag lifecycle is outside this
  plugin's cleanup responsibility.
- Keep dynamic help, `USAGE.md` fields, parser validation, and provider
  construction synchronized.
- Run config, provider, and plugin tests; include `engulf-docker-image-api` and
  `engulf-docker-image-core` tests when changing the recipe contract. Mock Docker
  in automated tests.
- Keep `PLUGIN_SCHEMA` aligned with every node variable and retain the
  last-running schema dependency. Run `make check-skill` after changes.
