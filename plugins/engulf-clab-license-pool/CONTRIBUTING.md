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
- Acquire the complete deterministic pool lease set before registry updates.
  Keep state transactions short, versioned, and atomic; never place license
  contents in user state.
- Preserve allocation preference, history, clamp exclusion, retry stability,
  pool-local regular-file selection, and deterministic lab-copy paths.
- Keep `sticky` as the compatibility default. Round-robin owns a pool-local
  sorted-file cursor; least-recently-used owns a monotonic pool-local use
  sequence. Every strategy reuses an active claim, excludes historical clamps
  while an ordinary choice remains, and records explicit clamp use.
- Keep `--eclab-license-pool-strategy` bound to the fixed-prefix
  `ECLAB_LICENSE_POOL_STRATEGY` runtime default. Strategy values are exactly
  `sticky`, `round-robin`, and `least-recently-used`.
- Use the shared topology editor to point only the derived topology at a copy.
  Never edit the selected YAML or consume a pool license in place.
- Record newly created claims and copies in invocation context before later
  preparation can fail. On any unsuccessful deploy outcome, roll back exactly
  that set while preserving pre-existing retry claims. Release one workspace
  after successful destroy and preserve destroy-all semantics.
- Freeze prompts must accept one file, directory pool, or `$VARIABLE`, with
  node-specific noninteractive values before the global value. Never log the
  resolved path or content as a diagnostic secret.
- Log one info-level selected-license diagnostic per node only after its
  lab-local copy succeeds. Include the node and source basename through `%r`
  logger arguments; never include the resolved source or generated-copy path.
- Keep runtime help, `USAGE.md`, freeze redaction, MCP profile restrictions, and
  state tests synchronized.
- Run frozen-prompt tests plus parser/writer/freeze tests after behavior changes.
  Use temporary dummy files; never use real licenses. Keep `PLUGIN_SCHEMA`
  synchronized with fixed-prefix and edition-aware license controls.

## Validation

Run the narrowest checks that exercise the changed boundary:

```bash
.venv/bin/python -m compileall -q plugins/engulf-clab-license-pool/src
.venv/bin/python -m pytest -q plugins/engulf-clab-license-pool/tests
make check-skill
```

Run the `engulf-clab-freeze` suite after changing the license label contract.

Use `./build.sh` in this directory for a distribution build, and `git diff --check`
before committing. Never run real deploy/destroy, Docker builds, Git clones, or
privileged MCP installation as part of validation.
