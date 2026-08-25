# Plugin Instructions

This package publishes the call-scoped immutable source topology and deferred
mutation API. Do not write topology files here.

- Keep plugin ID `engulf_clab.lab_parser`, priority `100`, and context ID
  `engulf_clab.topology.session` stable for dependent distributions.
- Parse and publish topology sessions only for deploy with a local filesystem
  topology. For implicit destroy, contribute the single non-writer source as an
  explicit topology while preserving explicit topology and name selection.
  Keep all selection and parse validation side-effect free; publish the session
  only in preparation.
- Preserve all supported Containerlab topology option forms and deterministic
  one-file discovery. Reject ambiguous/missing selections instead of guessing.
- Safe-load YAML and require a top-level mapping. Do not perform feature-specific
  mutation or full Containerlab semantic validation here.
- Keep the recursively frozen original, deep-copy access, copied operation
  values, owner attribution, path validation, delete precedence, conflict
  detection, and deterministic materialization phases.
- Do not expose mutable internal source data or retain callback-bound API/session
  handles beyond an invocation.
- Treat public imports, context IDs, path/operation semantics, and state-free
  behavior as a shared compatibility contract. Update `CONTRIBUTING.md` API
  detail and tests together; keep `USAGE.md` lab-facing.
- Run parser tests plus writer and every direct topology-mutator suite after a
  contract change. Use temporary YAML only; never deploy. Preserve schema
  registration before the generator's terminal preprocessing position.
