# Docker Image API Instructions

- Keep this package application-neutral and import only `engulf_api`.
- Do not parse Dockerfiles, inspect paths, invoke Docker, or import eclab code.
- Keep exported data immutable and validate/copy caller-owned collections.
- Preserve goal and context identifiers within API major 1.
- Keep `DOCKER_IMAGE_PROVENANCE_CONTEXT` typed by
  `DockerImageProvenanceSnapshot`; records describe selected Docker image
  providers with one record per resolved image.
- Do not add vrnetlab source-provider IDs or source fingerprints to this Docker
  registry. The vrnetlab build API owns a separate per-node source registry.
- Keep the public Docker provenance context safe to leave unread by publishing
  with `allow_unused=True`; this suppresses warnings only and does not grant
  access.
- Preserve resolver-attributed Docker provider IDs, recipe kinds, dependency
  edges, authority, fallback policy, and observed execution action.
- Do not put persistence code in this application-neutral API. The eclab adapter
  stores only sanitized record fields and restores them into context each call.
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
