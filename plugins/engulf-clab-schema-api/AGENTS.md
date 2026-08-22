# Schema API development notes

- This distribution is a stable contract package, not an Engulf plugin. It has
  no entry points and must not import the `engulf` runtime.
- Keep builder validation deterministic and free of filesystem access. Read and
  snapshot references only inside `record_plugin_schema()` while its API is live.
- Context values are immutable tuples and frozen records. Never store callback
  API, logger, state, or lease objects.
- Changes to exported models require direct-consumer tests in the schema
  generator, develop-skill plugin, and every maintained contributor.
- Validate with `.venv/bin/python -m pytest -q plugins/engulf-clab-schema-api/tests`.
