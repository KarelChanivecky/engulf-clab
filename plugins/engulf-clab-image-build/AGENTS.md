# Image Build Adapter Instructions

- Keep this plugin a thin eclab adapter around `engulf-docker-image-core`.
- Do not import any concrete provider or parse provider-owned node controls.
- Use only valid Containerlab node `image` fields as implicit roots.
- Keep `ECLAB_IMAGE_PARAM_*` local to its node image; do not introduce controls
  that copy parameters into recursive dependencies.
- Merge materialized topology roots with invocation graph fragments after
  mutators and before writer serialization.
- Build only in `prepare_call`; keep analysis side-effect free.
- Provision every literal root through ranked offers, including the low-authority
  pull fallback, then force `image-pull-policy: Never` only in the derived topology.
- Accept source image expressions after the parser eagerly resolves them from
  the effective call environment; reject only expressions still unresolved in
  the materialized topology because they prevent complete graph ownership.
- Preserve the legacy Docker build jobs option and environment fallback.
- Keep essential recursive image behavior in primary schema metadata; do not
  hide it exclusively behind a packaged usage reference.
- Keep schema, help, USAGE, dependencies, ordering, and tests synchronized.
