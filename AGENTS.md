# Repository Instructions

This repository is a Python 3.14 monorepo for an Engulf-based Containerlab
wrapper and separately publishable Engulf plugin packages.

## Layout

- `engulf-clab/` contains the wrapper application distribution.
- `plugins/` contains one directory per plugin distribution.
- `mcp-server/` contains the separately publishable local privileged control
  service and unprivileged stdio bridge.
- `plugins/engulf-clab-schema-api/`, `plugins/engulf-clab-schema/`, and
  `plugins/engulf-clab-develop-lab-skill/` own runtime schema declaration,
  compilation, and generated Codex skill installation respectively.
- `CONTRIBUTING.md` is the human-facing development and validation guide;
  `skills/README.md` documents the runtime-generated skill lifecycle.
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

- Plugin packages should declare `engulf-api>=1.0,<2` and
  `engulf-executable-wrapper-api>=1.0,<2`; plugin code imports neither runtime
  package.
- Derive adapters from `ExecutableWrapperPlugin`. `analyze_call()` must be
  side-effect free and returns an immutable `CallContribution`; put external
  work in `prepare_call()` and cleanup in `after_call()`. These callbacks use
  `InvocationAPI`.
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

- Treat the nearest package `README.md`, nearest `AGENTS.md`, dynamic plugin
  `help()`, source contract, and tests as one documentation set. Review all of
  them when behavior changes.
- A publishable package README documents installation, activation, exact
  topology/CLI/environment syntax, edition-prefix behavior, prerequisites,
  lifecycle, state/leases, cleanup, security implications, and troubleshooting.
- An `AGENTS.md` documents non-obvious code ownership, plugin/context ordering,
  invariants, prohibited behavior, and the narrow validation commands for that
  package. Do not merely repeat user-facing README prose.
- Containerlab YAML remains the base topology language. Link to the upstream
  `schemas/clab.schema.json` for base syntax and describe plugin controls as
  conventions layered onto valid Containerlab fields.
- Dynamic help is the installed runtime's feature inventory. Render exact
  edition-aware keys from callback-bound application metadata and keep help
  concise enough to scan while pointing to any secondary discovery option.
- Keep examples generic and safe. Never commit credentials, license contents,
  private repository URLs, privileged profile paths, or service secrets.
- Plugin README and `AGENTS.md` files referenced with `PluginSchema.refer()` are
  snapshotted from the installed distribution and embedded during compilation.

## Skill Package Requirements

- Keep the static template in `plugins/engulf-clab-develop-lab-skill/skill/`
  concise and put runtime detail in the compiler-generated `references/` tree.
- The generated skill name, command, and prompt must derive from callback-bound
  application metadata. Install atomically, back up only recognized generated
  targets, refuse symlinks and unknown targets, and retain fingerprinted runtime
  snapshots for existing conversations.
- Every runtime control needs a `PluginSchema` declaration with a one-line
  explanation of at most 240 characters. Use packaged `refer()` snapshots for
  detailed material.
- Reject vendor-specific assumptions in the generic skill. Runtime and edition
  selection must come before plugin-specific authoring, and runtime help remains
  authoritative for installed availability.
- Read `skills/README.md` for install, hook, package, validation, and release
  details before modifying skill tooling.

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
- Check installed documentation surfaces with `.venv/bin/eclab --help`,
  `.venv/bin/eclab --engulf-plugin-list`, and any advertised secondary help.
- Run `make check-skill` after schema, plugin behavior, or generated-skill
  changes. Validate a release candidate by building the three schema/skill
  packages and invoking the edition-aware install command against a temporary
  configuration root.
- Commits that change wrapper, plugin, MCP, schema, skill, or referenced
  documentation paths need exactly one `Skill-Impact: updated` or
  `Skill-Impact: none` trailer. Use `updated` when declarations, compilation, or
  the generated skill contract changes.
