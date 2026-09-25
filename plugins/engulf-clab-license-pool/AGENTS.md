# Plugin Instructions

License allocation is user-scoped shared state. Hold all affected pool leases
while claiming or releasing licenses; source topologies are modified only
through the shared topology editor.

- Derive from `SchemaBackedPlugin`. Bind global `--eclab-license` to persistent
  `ECLAB_LICENSE`, read only the normalized event environment, and preserve
  arbitrary pool variables plus node-specific `ECLAB_LICENSE_*` inputs.
- Keep plugin ID `engulf_clab.license_pool`, parser/writer dependencies, and
  workspace-plus-UUID claim identity stable.
- Use the fixed `ECLAB` prefix (`plugin.LABEL_PREFIX`) for clamp keys, frozen
  prompt markers, and noninteractive license keys — never derive these from
  application metadata. The lab-local state directory (`LicenseContract.
  state_directory`) is the one thing that stays derived from callback-bound
  short product metadata, using the same uppercase/underscore normalization;
  keep this split intentional rather than reusing one prefix for both.
- Parse pool and frozen-prompt requests in preparation, never help or analysis
  side effects. Validate topology mappings, environment values, pool/file roles,
  UUIDs, and clamp strings before copying.
- Resolve license selectors, pool clamps, allocation identities, and frozen
  prompts from the parser's immutable `EffectiveNode` snapshots; inherited
  values at defaults, kind, group, and node scope must behave identically.
- Acquire the complete deterministic pool lease set before registry updates.
  Keep state transactions short, versioned, and atomic; never place license
  contents in user state.
- Keep `init-license-pool [PATH] [--kind KIND]` a user-state control command.
  Canonical paths are unique and ordered; re-registration updates the kind in
  place. Consume only the first positional path and the plugin-owned `--kind`;
  ignore unclaimed extension arguments instead of rejecting them. Prune missing
  registered directories during deploy-time discovery. Return `None` from
  `before_goal` after registration and preempt Containerlab through an
  `analyze_call()` contribution so every plugin can observe the command.
- Match registered pools against the effective node `kind`. Explicit
  `ECLAB_AUTO_LICENSE` always requests automatic allocation; an unresolved
  license `$VARIABLE` requests it unless effective node env sets
  `ECLAB_DISABLE_AUTO_LICENSE=true`.
- Preserve an active automatic claim across retries. Otherwise scan matching
  registered pools in registration order and select from the first pool with
  an available license under the invocation's configured strategy.
- Preserve allocation preference, history, clamp exclusion, retry stability,
  pool-local regular-file selection, and deterministic lab-copy paths. Sticky
  selection prefers the claim's historical file before a never-used file.
- `least-recently-used` is the default strategy. Round-robin owns a pool-local
  sorted-file cursor; least-recently-used owns a monotonic pool-local use
  sequence. Every strategy reuses an active claim, excludes historical clamps
  while an ordinary choice remains, and records explicit clamp use.
- Keep `--eclab-license-pool-strategy` bound to the fixed-prefix
  `ECLAB_LICENSE_POOL_STRATEGY` runtime default. Strategy values are exactly
  `sticky`, `round-robin`, and `least-recently-used`.
- Use the shared topology editor to point only the derived topology at a copy.
  Never edit the selected YAML or consume a pool license in place.
- On any unsuccessful deploy or redeploy outcome, release only claims and copies first
  created by that invocation; preserve pre-existing retry claims. Use
  `prepare_failed` when a later plugin fails preparation, and unwind this
  plugin's own partial preparation before re-raising. Release one workspace
  after successful destroy and preserve destroy-all semantics.
- Keep parser, writer, and schema ordering in packaging dependency entry points,
  never on the runtime plugin object.
- Freeze prompts must accept `auto`, one file, directory pool, or `$VARIABLE`,
  with node-specific noninteractive values before the global value;
  `--eclab-auto-license` requests registered-pool allocation for every
  unresolved prompt. Never log the
  resolved path or content as a diagnostic secret.
- Log one info-level selected-license diagnostic per node only after its
  lab-local copy succeeds. Include the node, source basename, and selected pool
  through `%r` logger arguments; direct-file selections use `None` for the pool.
  Never include the resolved source or generated-copy path.
- Keep runtime help, `USAGE.md`, freeze redaction, MCP profile restrictions, and
  state tests synchronized.
- Run frozen-prompt tests plus parser/writer/freeze tests after behavior changes.
  Use temporary dummy files; never use real licenses. Keep `PLUGIN_SCHEMA`
  synchronized with fixed-prefix and edition-aware license controls.
