# Docker Image API Instructions

- Keep this package application-neutral and import only `engulf_api`.
- Do not parse Dockerfiles, inspect paths, invoke Docker, or import eclab code.
- Keep exported data immutable and validate/copy caller-owned collections.
- Preserve goal and context identifiers within API major 1.
- Provider callbacks are discovery-only and must remain side-effect free.
- Keep requirement parameters local to that exact image; do not copy them
  between requirements.
- Keep authority, terminal rejection, and execution fallback policy explicit in
  responses; never make registry availability checks part of discovery.
- Keep `DockerPullRecipe.only_if_missing` explicit and default it to false so
  provider-authored mirror pulls retain their existing always-pull behavior.
- Keep `DockerArchiveRecipe` a descriptor: an absolute archive path, an optional
  explicit source reference, and a missing-only flag. Never read, extract, or
  validate archive contents in this package.
- Update exports, docs, and direct-consumer tests with every contract change.
