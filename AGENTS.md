# Repository Instructions

This repository is a Python 3.14 monorepo for an Engulf-based Containerlab
wrapper and separately publishable Engulf plugin packages.

## Layout

- `engulf-clab/` contains the wrapper application distribution.
- `plugins/` contains one directory per plugin distribution.
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
