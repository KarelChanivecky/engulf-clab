# Schema API development notes

- This distribution is a stable contract package, not an Engulf plugin. It has
  no entry points and may import `engulf-api` and
  `engulf-executable-wrapper-api`, but never the `engulf` runtime.
- Keep builder validation deterministic and free of filesystem access. Read and
  snapshot references only inside `record_plugin_schema()` while its API is live.
- Keep the physical registry context ID fixed. Its value is an immutable
  `SchemaRegistry` partitioned by normalized pipeline IDs; contributions and
  pipeline declarations are frozen records. Never store callback API, logger,
  state, or lease objects.
- `eclab` is the default root for source compatibility. A child has one parent,
  every declaration is inheritable, and `{short_product}` expansion always uses
  callback-bound metadata from the running executable.
- Cache negotiation stays declarative: consumers may report an installed bundle
  fingerprint in `SchemaBuildRequest`, while the terminal generator alone owns
  cache validation and compilation. Requests and compiled bundle lookups must
  name their pipeline explicitly outside base eclab.
- Keep schema-backed registration import-time only: expand options and
  annotations from callback-bound application metadata without reading
  references, compiling schemas, touching state, or accessing the network.
- Environment-backed flags are wrapper-global compatibility replacements. The
  named runtime variable must be declared first; CLI normalization and
  completion execution belong to the executable-wrapper runtime.
- Changes to exported models require direct-consumer tests in the schema
  generator, develop-skill plugin, and every maintained contributor.
- Validate with `.venv/bin/python -m pytest -q plugins/engulf-clab-schema-api/tests`.
