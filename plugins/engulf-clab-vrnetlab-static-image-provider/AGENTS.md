# Plugin Instructions

This distribution is the concrete local-file source provider for the shared
vrnetlab builder. It owns image-source selection, topology controls, CLI flags,
environment aliases, and their help/schema declarations. It does not stage
qcow2 files, invoke Make or Docker, or register a Docker image recipe.

## Compatibility

- Wrapper plugin ID: `engulf_clab.vrnetlab_static_image_provider`
- Import package: `engulf_clab_vrnetlab_static_image_provider`
- Shared API distribution: `engulf-clab-vrnetlab-build-api`
- Shared builder plugin: `engulf_clab.vrnetlab_build`
- Shared invocation context: `org.engulf.clab.vrnetlab-build.sources`

## Development Notes

- Keep every source-selection flag, YAML environment field, fallback alias,
  precedence rule, and completion provider in this package.
- Resolve relative sources against the selected topology directory and publish
  only absolute paths through a `VrnetlabBuildAPI` constructed with the
  invocation context. Omit its node argument only for one common fallback
  source whose fallback users all share one `ECLAB_VRNETLAB_TYPE`; the API
  defaults that argument to `default`.
- Do not write the same API node key twice. Conflicts from this or another
  provider must fail instead of masking an earlier source.
- Publish the validated build-jobs option through
  `VrnetlabBuildAPI.set_build_jobs()`; the builder reads it without knowing
  this provider's option spelling.
- Keep `analyze_call()` side-effect free. Populate the invocation context in
  `prepare_call()` after topology parsing and before the shared builder.
- Declare `engulf-clab-vrnetlab-build` as a hard packaging dependency and order
  this provider before it with the dependency entry-point declaration. Preserve
  the parser and schema edges there as well. The builder owns the ensure-vrnetlab
  dependency and checkout ordering.
- Use the fixed `ECLAB` label/environment prefix across editions. Do not derive
  it from product metadata.
- Keep freeze discovery read-only and independent of the shared build lifecycle.
  It may allow unresolved source variables only when describing a portable
  freeze; normal deployment must reject them.
- Keep `PLUGIN_SCHEMA`, dynamic help, `USAGE.md`, option completion, and
  source precedence synchronized. Provider help must make the shared builder
  and installed-provider availability clear.
