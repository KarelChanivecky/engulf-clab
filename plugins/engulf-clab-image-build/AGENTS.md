# Image Build Adapter Instructions

- Keep this plugin a thin eclab adapter around `engulf-docker-image-core`.
- Do not import any concrete provider or parse provider-owned node controls.
- Use only valid Containerlab node `image` fields as implicit roots.
- Resolve inherited images and env parameters with shared EffectiveNode values,
  and force derived pull policy for inherited roots as well as explicit ones.
- Keep `ECLAB_IMAGE_PARAM_*` local to its node image; do not introduce controls
  that copy parameters into recursive dependencies.
- Merge materialized topology roots with invocation graph fragments after
  mutators and before writer serialization.
- Build only in `prepare_call`; keep analysis side-effect free.
- After provisioning and derived-topology policy mutation both succeed, publish
  the immutable `DockerImageProvenanceSnapshot` for every resolved image. Never
  publish a partial snapshot when preparation fails.
- Hydrate Docker image provenance from this plugin's WORKSPACE state in
  `before_goal` on every call. Persist completed deploy/redeploy calls in
  `after_call`, storing only image-provider IDs, actions, policy, dependencies,
  and recipe kinds. Do not store recipes, source-provider IDs, or local paths.
- Keep the public Docker provenance write marked `allow_unused=True`; consumers
  are optional and may be absent from a successful invocation.
- Declare lab-parser, lab-writer, and schema ordering only in
  `engulf.plugins.v1.dependency.engulf_clab_image_build` package metadata. Do
  not restore `plugin_dependencies`; Engulf rejects code-declared edges.
- Provision every literal root through ranked offers, including the low-authority
  local-or-pull fallback, then force `image-pull-policy: Never` only in the
  derived topology.
- Accept source image expressions after the parser eagerly resolves them from
  the effective call environment; reject only expressions still unresolved in
  the materialized topology because they prevent complete graph ownership.
- Preserve the legacy Docker build jobs option and environment fallback.
- Preparation holds image leases only while provisioning and creates no
  transient resource to release. Built images and Docker cache are durable
  outputs retained even when a later preparer fails, so this plugin needs no
  `prepare_failed()` override.
- Keep essential recursive image behavior in primary schema metadata; do not
  hide it exclusively behind a packaged usage reference.
- Keep schema, help, USAGE, dependencies, ordering, and tests synchronized.
