# Plugin instructions

- Read `CONTRIBUTING.md`, `USAGE.md`, source, schema, help, and tests as one contract.
- Keep `consumption` read-only and preempt it in `before_goal`.
- Keep Docker interaction behind the client boundary and mock it in tests.
- Preserve `N/A` propagation, inode and image-ID deduplication, retained-image
  fallback, lab-owner sharing semantics, and two-second polling.
- Declare ordering in `pyproject.toml`; never set `plugin_dependencies` in code.
- Run the package tests and `make check-skill` after schema or referenced-doc changes.
