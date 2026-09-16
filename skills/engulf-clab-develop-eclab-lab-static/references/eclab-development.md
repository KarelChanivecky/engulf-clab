# Repository Instructions

This repository is a Python 3.12+ monorepo for an Engulf-based Containerlab
wrapper and separately publishable Engulf plugin packages.

## Layout

- `engulf-clab/` contains the wrapper application distribution.
- `plugins/` contains one directory per plugin distribution.
- `mcp-server/` contains the separately publishable local privileged control
  service and unprivileged stdio bridge.
- `skills/engulf-clab-develop-eclab-lab-static/` contains the canonical, separately publishable
  Codex skill and its generated reference snapshots.
- `CONTRIBUTING.md` is the human-facing development and validation guide;
  `skills/README.md` is the authoritative skill-maintenance guide.
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
- After editing any mirrored README or `AGENTS.md`, run
  `ENGULF_DIR=<checkout> make update-skill`; do not hand-edit its generated
  counterpart in `skills/engulf-clab-develop-eclab-lab-static/references/`.

## Skill Package Requirements

- Keep `skills/engulf-clab-develop-eclab-lab-static/SKILL.md` under 500 lines and focused on the
  core procedure. Put detailed API, plugin, schema, and troubleshooting context
  in one-level-deep `references/` files and route them directly from the skill.
- Keep frontmatter limited to `name` and `description`. The description must
  state both capability and triggering contexts. Keep `agents/openai.yaml`
  aligned with the definition and use `$develop-eclab-lab` in its default
  prompt.
- The pip wheel must embed `SKILL.md`, `agents/`, and `references/`; an installed
  skill must not depend on this repository. The installer must publish through
  a staging directory, preserve recognized previous installations as backups,
  and refuse unknown destinations.
- Update `LOCAL_SOURCES`, `ENGULF_SOURCES`, normalizations, and
  `references/source-index.md` together when changing bundled context.
  Normalizations may genericize examples but must not conceal behavior
  differences.
- Reject vendor-specific assumptions in the generic skill. Runtime and edition
  selection must come before plugin-specific authoring, and runtime help remains
  authoritative for installed availability.
- Read `skills/README.md` for install, hook, package, validation, and release
  details before modifying skill tooling.

## Development Notes

- Use the local `.venv` for validation when present.
- The local `.venv` should contain Python 3.12 or newer plus the installed
  `engulf` and `engulf-api` packages from `../cliwrap` when testing local
  runtime changes.
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
- Run `make check-skill` after behavior or documentation changes and inspect
  every regenerated reference diff. Validate a release candidate by building
  the skill wheel, installing it into a temporary virtual environment and
  skills directory, and running `develop-eclab-lab-static-install --check`.
- Commits that change wrapper, plugin, MCP, or mirrored documentation paths need
  exactly one `Skill-Impact: updated` or `Skill-Impact: none` trailer. Use
  `updated` only with a staged skill change.
