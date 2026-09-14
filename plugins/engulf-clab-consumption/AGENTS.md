# Plugin instructions

- Read `CONTRIBUTING.md`, `USAGE.md`, source, schema, help, and tests as one contract.
- Keep Docker, topology, and filesystem measurement read-only. Preempt
  `consumption` in `before_goal`.
- Keep Docker interaction behind the client boundary and mock it in tests.
- Preserve `N/A` propagation, inode and image-ID deduplication, retained-image
  fallback, `DEPLOYED`/`STOPPED`/`RECLAIMED` state, lab-owner sharing semantics,
  and two-second polling.
- Consume and contribute inventory only through `engulf-clab-lab-registry-api`;
  do not read registry state or observe deploy lifecycle here.
- Declare ordering in `pyproject.toml`; never set `plugin_dependencies` in code.
- Run the package tests and `make check-skill` after schema or referenced-doc changes.
