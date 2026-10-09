# Generated lab skill contribution notes

- This provider remains `SchemaAudience.SUPPORT` and is active only when the
  callback-bound short product is exactly `eclab`.
- The shared `engulf-clab-skill-collector` owns the `install-skills` command,
  target state, installation, and refresh. This plugin owns only schema-build
  requests and materializing a generated skill directory.
- Declare the schema dependency edge in packaging with
  `preprocess=after; postprocess=before`, so schema compilation sees the
  contribution and this provider can consume the compiled result afterward.
- Declare the collector edge with
  `preprocess=before; postprocess=after`: it publishes tracked skill names
  before this provider and installs the generated path after this provider.
- Write each generated source into a unique per-invocation directory under this
  plugin's user state, then call `record_temporary_skill()` with its absolute
  path. Declare `SKILL_TEMPORARY_PATHS_CONTEXT` in reads and writes. Shared
  context must contain only paths, never rendered files or `CompiledSchemaBundle`.
- Request a strict schema build for explicit `install-skills`; request a
  best-effort build only when the collector reports `develop-eclab-lab` tracked.
  Help and internal completion must not request schema generation.
- Preserve the concise template and fingerprinted runtime references. The
  collector copies the complete rendered directory and owns safe replacement.
- The collector removes temporary source trees after each collection attempt;
  process-exit cleanup removes its process-owned state, and the next generator
  reaps state left by an exited process.
