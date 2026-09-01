# Repository Instructions

This repository is a Python 3.14 monorepo for an Engulf-based Containerlab
wrapper and separately publishable Engulf plugin packages.

## Layout

- `engulf-clab/` contains the wrapper application distribution.
- `plugins/` contains one directory per plugin distribution.
- `mcp-server/` contains the separately publishable local privileged control
  service and unprivileged stdio bridge.
- `plugins/engulf-clab-schema-api/`, `plugins/engulf-clab-schema/`, and
  `plugins/engulf-clab-develop-eclab-lab/` own runtime schema declaration,
  compilation, and generated Codex skill installation respectively.
- `CONTRIBUTING.md` is the human-facing development and validation guide;
  `skills/README.md` documents the runtime-generated skill lifecycle.
- `skills/engulf-clab-develop-eclab-lab-static/` is the frozen pre-generator
  comparison skill. Keep its substantive workflow stable; identity and packaging
  fixes may change only when needed to keep it installable beside the generated target.
- Each plugin directory must be self-contained and publishable as its own Python
  package.

## Engulf Conventions

- Wrapper applications import the `engulf` runtime.
- Plugin packages import `engulf_api`, not `engulf`.
- The wrapper application ID is `engulf-clab`.
- The wrapper's canonical workspace is the directory containing an explicitly
  selected topology, or the current directory when no filesystem topology is
  selected. Keep this identity stable for persisted workspace state.
- The wrapper uses `ExecutableWrapperGoal` and `PluginPolicy.declared()`.
- The standard Containerlab goal opts into trusted native completion sourcing. Keep
  that application-level choice explicit; generic executable wrappers must not source
  arbitrary child output, and custom `ContainerlabApp` callers may disable it.
- Plugins for this wrapper must publish a goal catalog declaration and an
  application declaration, both with the exact plugin ID as their entry-point
  name:

```text
engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper
engulf.plugins.v1.application.engulf_clab
```

- Plugin packages should declare `engulf-api>=1.2,<2` and
  `engulf-executable-wrapper-api>=1.2,<2`; plugin code imports neither runtime
  package. `1.2` is the floor for packaging-declared plugin dependencies and the
  `prepare_failed()` unwind callback.
- Declare plugin ordering in packaging, never in code. Engulf 0.2 rejects a
  plugin that sets `plugin_dependencies` and loads the edges from the
  distribution's dependency entry-point group instead:

```toml
[project.entry-points."engulf.plugins.v1.dependency.engulf_clab_example"]
"engulf_clab.schema" = "preprocess=after; postprocess=none"
```

  The group name is the declaring plugin's ID with dots replaced by underscores,
  each entry name is the plugin depended on, and the value sets both positions
  (`before`, `after`, or `none`). Assert the declaration in the package's own
  tests so a refactor cannot silently drop an ordering edge.
- Derive adapters from `ExecutableWrapperPlugin`. `analyze_call()` must be
  side-effect free and returns an immutable `CallContribution`; put external
  work in `prepare_call()` and cleanup in `after_call()`. These callbacks use
  `InvocationAPI`.
- A plugin whose `prepare_call()` mutates host state, claims a shared resource,
  or copies files must unwind that work on both failure paths. Roll back only
  what this invocation created: record it in a private invocation context, and
  never release a claim that a previous successful deploy still owns. Plugins
  that only write invocation context need no unwind, since context is discarded
  with the invocation.
  - **A later plugin failed**: `prepare_failed()` runs, in reverse preparation
    order, for every plugin that already prepared. The goal dispatches
    `prepare_call()` one plugin at a time and tracks progress itself, so this
    covers anything that ends the phase — a raised exception, `SystemExit`, and
    a `KeyboardInterrupt` arriving mid-preparation all unwind identically.
  - **This plugin itself failed**: `prepare_failed()` is *never* dispatched to
    the plugin that raised, so every recipient knows it prepared fully without
    inspecting the event. Release this attempt's partial work in a failure
    handler inside `prepare_call()`:

```python
try:
    ...  # claim resources, tracking what this attempt claimed
except BaseException:
    release(claimed)
    raise
```

    `BaseException`, not `Exception`: an interrupt is not an `Exception`, so a
    narrow catch strands this plugin's own work even though every plugin before
    it unwinds. A failure handler, not `finally`: cleanup here is conditional on
    failing, and `finally` needs a `prepared` flag that every early `return` must
    set — miss one and it releases what a successful preparation just built. The
    bare `raise` keeps the wide catch clear of blind-except lint, so the correct
    shape is also the one a linter accepts.
  - The two paths differ in lock state, so one shared helper cannot serve both.
    Inside `prepare_call()` the leases that callback took are still held, because
    `deactivate()` has not run. By the time `prepare_failed()` is dispatched the
    preparing callback was deactivated and `release_active()` freed them, and a
    lease context carried over from that activation would fail `require_current`.
    Keep the lease-acquiring entry point separate from the release itself, and
    call the release directly from `prepare_call()`. Acquiring there raises
    `RuntimeError: nested or overlapping resource leases are not allowed`, which
    then replaces the real failure in `PluginCallbackError.error` and is what
    every downstream plugin sees in diagnostics.
  - `after_call()` does not run when preparation fails, because no call was
    attempted, and `after_goal()` still does not run on an interrupt. Keep
    durable state recoverable by a later `destroy` or by a provisioning journal
    replayed on the next run; preparation unwind is guaranteed, invocation-scoped
    cleanup on interrupt is not.
- Annotate `help()` with executable-wrapper `HelpAPI` and registration callbacks
  with `RegistrationAPI`. Emit diagnostics only through callback-bound
  `api.logger`; never configure logging or print operational messages directly.
- Use `api.leases()` for long-running shared host resources and short
  `StateStore.transaction()` blocks for state read-modify-write operations.
- Do not use the legacy local plugin directory loading model for production
  plugins. Plugins should be installed/discovered as Python packages.

## Plugin Package Requirements

Every new plugin added under `plugins/` must include:

- Its own `AGENTS.md` with plugin-specific development notes.
- Its own `USAGE.md` with the complete operator-facing contract.
- Its own `CONTRIBUTING.md` with contributor-facing implementation guidance.
- A concise `README.md` that links to both documents.
- Its own MIT `LICENSE` file.
- A `pyproject.toml` with a package name, entry point, and dependencies.
- A `src/<import_package>/` package directory.
- A `src/<import_package>/py.typed` marker when the package is typed.

Use this copyright line in each plugin license:

```text
Copyright (c) 2026 Karel Chanivecky
```

Plugin IDs must be globally unique, lowercase, dot-qualified identifiers, for
example `engulf_clab.example`.

## Documentation Requirements

- Treat the nearest package `README.md`, `USAGE.md`, `CONTRIBUTING.md`, nearest
  `AGENTS.md`, dynamic plugin `help()`, source contract, and tests as one
  documentation set. Review all of them when behavior changes.
- A publishable package `USAGE.md` documents installation, activation, exact
  topology/CLI/environment syntax, edition-prefix behavior, prerequisites,
  lifecycle, state/leases, cleanup, security implications, and troubleshooting.
- A package `CONTRIBUTING.md` documents non-obvious code ownership,
  plugin/context ordering, invariants, prohibited behavior, and narrow validation
  commands. `AGENTS.md` keeps the repository instructions needed by coding agents
  aligned with that contributor contract; neither repeats user-facing usage prose.
- Containerlab YAML remains the base topology language. Link to the upstream
  `schemas/clab.schema.json` for base syntax and describe plugin controls as
  conventions layered onto valid Containerlab fields.
- Dynamic help is the installed runtime's feature inventory. Render exact
  edition-aware keys from callback-bound application metadata and keep help
  concise enough to scan while pointing to any secondary discovery option.
- Keep examples generic and safe. Never commit credentials, license contents,
  private repository URLs, privileged profile paths, or service secrets.
- Runtime-facing `USAGE.md` files referenced with `PluginSchema.refer()` are
  snapshotted from the installed distribution and embedded during compilation.
  Do not embed `CONTRIBUTING.md` or `AGENTS.md` in generated lab skills.

## Skill Package Requirements

- Keep the static template in `plugins/engulf-clab-develop-eclab-lab/skill/`
  concise and put runtime detail in the compiler-generated `references/` tree.
- The bundled eclab generated-skill command, target, prompt, and pipeline are
  static and must be gated to callback-bound `short_product_name == "eclab"`.
  External editions consume their own compiled pipeline bundle and own their
  skill tooling. Install atomically, back up only recognized generated targets,
  refuse symlinks and unknown targets, and retain fingerprinted runtime snapshots
  for existing conversations.
- Every runtime control needs a `PluginSchema` declaration with a one-line
  explanation of at most 240 characters. Use packaged `refer()` snapshots for
  detailed material.
- Reject vendor-specific assumptions in the generic skill. Runtime and edition
  selection must come before plugin-specific authoring, and runtime help remains
  authoritative for installed availability.
- Read `skills/README.md` for install, hook, package, validation, and release
  details before modifying skill tooling.
- Preserve `develop-eclab-lab-static` as an explicitly invoked comparison
  baseline. It must use a distinct distribution, command, import package, and
  install target from the runtime-generated `develop-eclab-lab` skill.

## Development Notes

- Use the local `.venv` for validation when present.
- The local `.venv` should contain Python 3.14 plus the installed `engulf` and
  `engulf-api` packages from `../cliwrap` when testing local runtime changes.
- Keep commits focused. Do not include `.venv`, build outputs, caches, or editor
  metadata.
- Use `rg` or `rg --files` for repository searches.
- Prefer `apply_patch` for manual source edits.
- After changing the wrapper or plugins, run the narrowest useful validation:
  bytecode compilation, package install checks, plugin discovery checks, or unit
  tests as appropriate for the change.
- Run direct-consumer tests after changing a shared contract: parser changes
  affect mutators/writer, container API changes affect manager/collections, and
  checkout changes affect both ensure plugins.
- When bumping a package version, sweep the dependency pins for it. Search every
  `pyproject.toml` in the repository (including `engulf-clab/` and `mcp-server/`)
  for the package name and raise any consumer floor that the new version breaks,
  bumping the consumer's own version when its `pyproject.toml` changes. Before
  publishing, install the full set into `.venv` and run `.venv/bin/pip check` —
  a successful publish does not clear a stale consumer pin, and the conflict only
  surfaces at install time on someone else's machine.
- Check installed documentation surfaces with `.venv/bin/eclab --help`,
  `.venv/bin/eclab --engulf-plugin-list`, and any advertised secondary help.
- Run `make check-skill` after schema, plugin behavior, or generated-skill
  changes. Validate a release candidate by building the three schema/skill
  packages and invoking the static eclab install command against a temporary
  configuration root.
- Commits that change wrapper, plugin, MCP, schema, skill, or referenced
  documentation paths need exactly one `Skill-Impact: updated` or
  `Skill-Impact: none` trailer. Use `updated` when declarations, compilation, or
  the generated skill contract changes.
