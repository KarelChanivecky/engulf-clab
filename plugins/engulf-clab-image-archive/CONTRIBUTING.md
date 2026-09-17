# Contributing

This directory contains the `engulf-clab-image-archive` plugin distribution.

## Ownership

`config.py` owns topology reading and validation, `provider.py` owns the pure
provider lookup, and `plugin.py` owns lifecycle, schema, and help. Recipe
execution — `docker load`, retag, and reuse — belongs to
`engulf-docker-image-core`; this package never runs Docker.

`topology.py` exposes the parser's immutable `EffectiveNode` snapshots, not a
private node model. Archive controls and image tags must come from that shared
view, matching the dispatcher's inherited roots and materialized mutations.

The distribution depends on `engulf-docker-image-core>=1.0.0` even though it
imports nothing from it: `DockerArchiveRecipe` has no executor in earlier
releases, and the floor keeps a stale resolver from failing the recipe kind at
build time.

It also depends directly on `engulf-clab-image-build>=0.1.1`: inherited image
roots require the same effective-node view. The packaging-level
ordering edge names that plugin as a hard dependency, and the adapter supplies
the dispatcher that consumes this provider during deploy and single-source redeploy.

## Invariants

- Keep the fixed `ECLAB` prefix in `config.LABEL_PREFIX`; never derive it from
  application metadata.
- `analyze_call` validates and never touches Docker. `prepare_call` refreshes the
  provider map before `engulf_clab.image_build` resolves the graph, which the
  packaging-declared `image_build` AFTER dependency guarantees. The lab-parser,
  image-build, and schema ordering edges belong only in the distribution's
  dependency entry-point metadata; Engulf rejects code-level declarations.
- The provider map is prepared state for one invocation. Clear it in
  `prepare_failed()` when a later plugin cannot prepare, in `after_call()` after
  any attempted call, and within this plugin's own exception path because a
  failing preparer does not receive `PreparationFailedEvent`.
- `provide()` must stay side-effect free and thread-safe: hold `self._lock` for
  the dictionary read only, and build the response from recorded values.
- Key recorded requests by canonical image reference so `example/router` and
  `example/router:latest` resolve to the same request.
- Preserve `fallback_on_failure=False`. A failed load must surface rather than
  reaching the dispatcher's pull fallback for the same tag.
- Preserve `only_if_missing = not request.reload` so an unchanged archive is not
  re-read on every deploy.
- Reject `ECLAB_IMAGE_ARCHIVE_REF` and `ECLAB_IMAGE_ARCHIVE_RELOAD` without
  `ECLAB_IMAGE_ARCHIVE`, non-literal image tags, unsupported archive suffixes,
  and missing archive files during analysis.
- Never mutate the topology. This plugin contributes a provider only; the
  dispatcher sets `image-pull-policy: Never` for provisioned roots.

## Validation

Run the narrowest checks that exercise the changed boundary:

```bash
.venv/bin/python -m compileall -q plugins/engulf-clab-image-archive/src
.venv/bin/python -m pytest -q plugins/engulf-clab-image-archive/tests
.venv/bin/python -m pytest -q plugins/engulf-docker-image-api/tests \
    plugins/engulf-docker-image-core/tests
make check-skill
```

Run `make build-<package>` for a distribution build (or `make build` for
every distribution), and `git diff --check` before committing. Never run real
deploy/destroy, Docker loads, or privileged MCP installation as part of
validation.
