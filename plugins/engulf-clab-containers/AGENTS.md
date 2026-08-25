# Container Manager Plugin Instructions

This is the only plugin that turns declarative container collections into
topology mutations. Keep collection discovery under normal Engulf activation,
accept only typed fields from `engulf-clab-containers-api`, and never mutate the
source topology. It must run after collections and the lab parser, and before
the Dockerfile builder and lab writer.

- Derive from `SchemaBackedPlugin` so discovery controls and advertised values
  participate in completion without parsing generated schema artifacts.
- Keep plugin ID `engulf_clab.containers`, collection context
  `engulf_clab.containers.collections`, and topology context declarations stable.
- Validate the complete catalog and proposed merge during `analyze_call()`;
  perform only deferred editor operations during `prepare_call()`.
- Use the fixed `ECLAB` Docker variable prefix (`manager.LABEL_PREFIX`). Never
  derive it from callback application metadata or the executable filename —
  injected node env vars must stay portable across editions.
- Preserve canonical `:latest` naming, namespace collision detection, package
  asset validation, required management networking, and conflict-safe merge
  rules. Do not silently override user fields or fall through malformed managed
  names to a registry pull.
- Keep user documentation explicit that source topologies declare the recipe
  kind. Injection is deploy-only, while other Containerlab commands parse the
  raw topology.
- The manager must not run Docker, import collection implementation modules
  directly, inspect undeclared fields, or retain state. The Dockerfile builder
  owns builds and the writer owns temporary-file cleanup.
- Keep `--eclab-containers-help` side-effect free and based only on active
  registered collections. Update runtime help and `USAGE.md` together when catalog
  syntax changes.
- Run manager tests, container API tests, and at least one installed core
  collection discovery/help check. Package-data behavior must be tested from a
  built wheel when paths or assets change.
- Record `PLUGIN_SCHEMA` during `before_goal`; the schema dependency must remain
  last and reference snapshots come from built package data. Run `make check-skill`.
