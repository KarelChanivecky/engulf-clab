# Plugin Instructions

The pure allocation contract lives in the sibling
`engulf-clab-license-pool-lib` distribution. Keep Engulf callbacks, leases,
state transactions, topology mutation, file copying, and diagnostics in this
plugin package; do not move framework imports into the library.

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
- Use `engulf_clab_lab_parser.effective_nodes()` for license, clamp, identity,
  and frozen-prompt reads. Do not inspect raw `topology.nodes` for values that
  Containerlab allows at defaults, kind, or group scope.
- Acquire the complete deterministic pool lease set before registry updates.
  Keep state transactions short, versioned, and atomic; never place license
  contents in user state.
- `init-license-pool [PATH] [--eclab-kind KIND] [--eclab-update]` canonicalizes
  an existing directory into ordered user-state registration. Interactive
  calls ask for a kind unless supplied; noninteractive calls retain the
  `fortinet_fortigate` default. Discover metadata contributors through the
  license-pool API, call them before taking the registry lease, then re-read,
  merge, and atomically publish their deltas under that lease before
  registration. Each contributor reuses existing declared variables unless
  update mode is requested; the collector resolves declarations in this order:
  explicit `--eclab-licence-pool-var`, contributor `resolve_variable_values`,
  existing value on ordinary init, interactive answer, then declared default.
  Pass only declared variable names and typed values from the contributor
  resolver. Optional variables without a default can be omitted interactively
  or noninteractively; other missing noninteractive values require an explicit
  value or default. Preserve unclaimed extension arguments.
  Keep `--kind` as a legacy alias and tolerate
  unclaimed extension arguments. Publish the registration result in invocation
  context so edition policy plugins can act after shared registration.
  Registration records its exit status and returns `None` from `before_goal`;
  `analyze_call()` preempts Containerlab only after all plugins have analyzed
  the command. Keep this plugin's `before_goal` priority above any edition
  adapter that reads the registration result in that phase; package lifecycle
  dependency edges do not order `before_goal` callbacks.
- For `defrost`, inspect registered pools in this plugin's own user state under
  the registry lease, then publish only `LicensePoolAvailability(registered)`
  through `LICENSE_POOL_AVAILABILITY_CONTEXT`. Never put pool paths in that
  shared context; consumers have separate plugin-scoped state.
- Automatic requests are either the explicit `ECLAB_AUTO_LICENSE` marker or an
  unresolved license `$VARIABLE` without effective
  `ECLAB_DISABLE_AUTO_LICENSE=true`. Match only registrations for the node's
  effective `kind`; preserve an active claim, otherwise try matching pools in
  registration order until one has an available license.
- Preserve allocation preference, history, clamp exclusion, retry stability,
  pool-local regular-file selection, and deterministic lab-copy paths. Sticky
  selection prefers the claim's historical file before a never-used file.
- Keep `least-recently-used` as the default. Round-robin owns a pool-local
  sorted-file cursor; least-recently-used owns a monotonic pool-local use
  sequence. Every strategy reuses an active claim, excludes historical clamps
  while an ordinary choice remains, and records explicit clamp use.
- Keep `--eclab-license-pool-strategy` bound to the fixed-prefix
  `ECLAB_LICENSE_POOL_STRATEGY` runtime default. Strategy values are exactly
  `sticky`, `round-robin`, and `least-recently-used`.
- Use the shared topology editor to point only the derived topology at a copy.
  Never edit the selected YAML or consume a pool license in place.
- Record newly created claims and copies in invocation context before later
  preparation can fail. Roll back exactly that set in `prepare_failed` when a
  later preparer raises, inside `prepare_call` when this plugin itself raises,
  and after any unsuccessful attempted deploy or redeploy, while preserving pre-existing
  retry claims. Release one workspace after successful destroy and preserve
  destroy-all semantics.
- Declare parser, writer, and schema ordering only in the package dependency
  entry-point group; do not restore `plugin_dependencies` on the plugin object.
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

## Validation

Run the narrowest checks that exercise the changed boundary:

```bash
.venv/bin/python -m compileall -q plugins/engulf-clab-license-pool/src
.venv/bin/python -m pytest -q plugins/engulf-clab-license-pool/tests
make check-skill
```

Run the `engulf-clab-freeze` suite after changing the license label contract.

Run `make build-<package>` for a distribution build (or `make build` for
every distribution), and `git diff --check` before committing. Never run
real deploy/destroy, Docker builds, Git clones, or
privileged MCP installation as part of validation.
