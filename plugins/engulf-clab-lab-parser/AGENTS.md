# Plugin Instructions

This package publishes the call-scoped immutable source topology and deferred
mutation API. Do not write topology files here.

- Keep plugin ID `engulf_clab.lab_parser`, priority `100`, and context ID
  `engulf_clab.topology.session` stable for dependent distributions.
- Parse and publish topology sessions only for deploy or single-source redeploy
  with a local filesystem topology. Preserve native `redeploy --all` and
  name-only handling. For destroy by source, prefer its retained writer topology when it
  exists; otherwise contribute the single non-writer source for implicit
  selection. Resolve a unique retained topology for name selection and preserve
  all-labs selection. Route the lab-reading commands that search for a topology
  the same way, and leave commands that act on every lab alone.
  Keep all selection and parse validation side-effect free; publish the session
  only in preparation.
- Preserve all supported Containerlab topology option forms and deterministic
  one-file discovery. Reject ambiguous/missing selections instead of guessing.
- Expand Containerlab shell-style environment expressions from the effective
  call environment before safe-loading YAML, then require a top-level mapping.
  Preserve unset expressions and escaped dollars exactly as Containerlab does.
  Do not perform feature-specific mutation or full semantic validation here.
- Keep the recursively frozen original, deep-copy access, copied operation
  values, owner attribution, path validation, delete precedence, conflict
  detection, and deterministic materialization phases.
- Do not expose mutable internal source data or retain callback-bound API/session
  handles beyond an invocation.
- Keep EffectiveNode inheritance centralized, with Go-compatible kind/group
  selection, defaults < kind < group < node precedence, immutable winning and
  shadowed origins, and a declaration inventory including unused kinds/groups.
  Preserve string-map YAML scalar spellings; do not invent removal markers.
- Declare the hard schema-plugin dependency only in the distribution entry-point
  metadata, with the schema dependency after this plugin in preprocessing. Never
  restore a code-level `plugin_dependencies` declaration.
- Treat public imports, context IDs, path/operation semantics, and state-free
  behavior as a shared compatibility contract. Update `CONTRIBUTING.md` API
  detail and tests together; keep `USAGE.md` lab-facing.
- Run parser tests plus writer and every direct topology-mutator suite after a
  contract change. Use temporary YAML only; never deploy. Preserve schema
  registration before the generator's terminal preprocessing position.
