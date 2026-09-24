# Package Instructions

This package defines the stable API shared by vrnetlab source providers and
the single builder. Preserve its public context ID and setter semantics.

- Keep source-path selection and all CLI/YAML/environment syntax out of this
  package.
- A path is absolute but need not exist yet; providers may download or create
  the input later in the same invocation.
- A node key, including `default`, may be written only once by default. The
  `override=True` API argument explicitly replaces its earlier value; callers
  must use it only when their source policy gives them precedence.
- Construct `VrnetlabBuildAPI` with the invocation-scoped context and use its
  methods for source declarations, coverage queries, and build-job limits.
- The default node name for `VrnetlabBuildAPI.set_image_source()` is `default`;
  builder lookup checks a node-specific entry before that default.
- `unprovisioned_nodes()` receives the candidate nodes from its caller and
  reports source-map coverage, not Docker image or build state.
- Use the managed `InvocationAPI` context and immutable snapshots for reads.
  Never retain invocation-bound APIs or handles.
- Keep API documentation aligned with `USAGE.md` and `CONTRIBUTING.md`.
