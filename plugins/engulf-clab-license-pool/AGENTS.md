# Plugin Instructions

License allocation is user-scoped shared state. Hold all affected pool leases
while claiming or releasing licenses; source topologies are modified only
through the shared topology editor.

- Keep plugin ID `engulf_clab.license_pool`, parser/writer dependencies, and
  workspace-plus-UUID claim identity stable.
- Parse pool and frozen-prompt requests in preparation, never help or analysis
  side effects. Validate topology mappings, environment values, pool/file roles,
  UUIDs, and clamp strings before copying.
- Acquire the complete deterministic pool lease set before registry updates.
  Keep state transactions short, versioned, and atomic; never place license
  contents in user state.
- Preserve allocation preference, history, clamp exclusion, retry stability,
  pool-local regular-file selection, and deterministic lab-copy paths.
- Use the shared topology editor to point only the derived topology at a copy.
  Never edit the selected YAML or consume a pool license in place.
- Release one workspace only after successful destroy. Preserve destroy-all
  semantics and remove only generated license copies owned by this plugin.
- Freeze prompts must accept one file, directory pool, or `$VARIABLE`, with
  node-specific noninteractive values before the global value. Never log the
  resolved path or content as a diagnostic secret.
- Keep runtime help, README, freeze redaction, MCP profile restrictions, and
  state tests synchronized.
- Run frozen-prompt tests plus parser/writer/freeze tests after behavior changes.
  Use temporary dummy files; never use real licenses. Regenerate the license
  skill references after changes.
