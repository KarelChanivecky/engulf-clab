# Contributing to engulf-clab

This monorepo releases the `eclab` wrapper, a local privileged MCP service,
independent Engulf plugin distributions, and a runtime-generated lab-development
Codex skill. A change is complete only when behavior, runtime help, package
documentation, schema declarations, and tests agree.

## Contents

- [Repository model](#repository-model)
- [Development environment](#development-environment)
- [Engulf plugin contract](#engulf-plugin-contract)
- [Adding or changing a plugin](#adding-or-changing-a-plugin)
- [Documentation contract](#documentation-contract)
- [Runtime schema and skill](#runtime-schema-and-skill)
- [Validation](#validation)
- [Commits and releases](#commits-and-releases)

## Repository model

| Path | Responsibility | Release unit |
| --- | --- | --- |
| `engulf-clab/` | Defines the `eclab` application and wraps Containerlab. | `engulf-clab` |
| `plugins/<distribution>/` | Implements one feature or shared typed contract. | One Python distribution per directory |
| `mcp-server/` | Provides the stdio bridge, privileged daemon, installer, and systemd unit. | `engulf-clab-mcp` |
| `plugins/engulf-clab-schema-api/` | Stable plugin schema declaration and invocation-state contract. | `engulf-clab-schema-api` |
| `plugins/engulf-clab-schema/` | Compiles Containerlab and active-plugin schemas at runtime. | `engulf-clab-schema` |
| `plugins/engulf-clab-develop-eclab-lab/` | Installs and refreshes the static base eclab generated skill. | `engulf-clab-develop-eclab-lab` |
| `plugins/engulf-docker-image-api/` | Stable application-neutral graph and provider contract. | `engulf-docker-image-api` |
| `plugins/engulf-docker-image-core/` | Recursive resolver, Dockerfile analyzer, scheduler, and reusable goal. | `engulf-docker-image-core` |

The wrapper imports the `engulf` runtime. Runtime plugins import the stable
`engulf_api` and `engulf_executable_wrapper_api` contracts, not their runtime
implementations. Contract-only packages should remain declarative and avoid
runtime discovery or host work.

Containerlab YAML is the source topology language. Validate its standard shape
against the upstream `schemas/clab.schema.json` before applying eclab plugin
conventions. Plugins must preserve the source topology and communicate changes
through the shared parser/writer pipeline.

## Development environment

Use Python 3.14. The repository-wide installer builds the neighboring Engulf
checkout, every local distribution, and an isolated development environment:

```bash
ENGULF_DIR=../cliwrap ./install-dev.sh
source .venv/bin/activate
python -m pip check
eclab --help
```

Set `VENV_DIR` to choose another virtual environment, `PYTHON` to choose the
bootstrap interpreter, and `ENGULF_DIR` to identify the Engulf checkout. The
script installs wheels rather than editable packages so entry-point discovery
matches a released installation. Rerun it after changing package metadata,
entry points, or the Engulf contracts.

Use `./uninstall-dev.sh` to uninstall the development distributions while
preserving the virtual environment. It accepts the same `VENV_DIR` override.

For a narrow package-only build, run its `build.sh`. Every package script accepts
normal `python -m build` arguments and honors `PYTHON` and `VENV_DIR`:

```bash
PYTHON="$PWD/.venv/bin/python" \
VENV_DIR="$PWD/.venv" \
plugins/engulf-clab-wan/build.sh
```

## Engulf plugin contract

All production wrapper plugins use the application ID `engulf-clab` and publish
the same plugin object under both entry-point groups, with the exact globally
unique plugin ID as the entry-point name:

```text
engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper
engulf.plugins.v1.application.engulf_clab
```

Follow these lifecycle rules:

1. Derive the adapter from `ExecutableWrapperPlugin`.
2. Keep `analyze_call()` side-effect free. Validate syntax and return an
   immutable `CallContribution` there.
3. Perform filesystem, process, Docker, Git, or host-network work only in
   `prepare_call()` after all analyzers accept the invocation.
4. Perform outcome-dependent cleanup in `after_call()`. Cleanup must tolerate a
   partially prepared call and preserve the wrapped command's result.
5. Unwind `prepare_call()` side effects on both failure paths. Release only what
   this invocation created — track it in a private invocation context — so a
   failed redeploy never tears down resources a previous successful deploy still
   owns. A plugin that writes only invocation context needs no unwind, because
   context dies with the invocation.
   - `prepare_failed()` covers a *later* plugin failing; it runs in reverse
     preparation order for every plugin that already prepared. The goal prepares
     one plugin at a time and tracks progress itself, so an exception,
     `SystemExit`, and a mid-preparation Ctrl-C all unwind the same plugins.
   - It is never dispatched to the plugin that raised, so every recipient knows
     it prepared fully. A `prepare_call()` that has already changed something
     undoes this attempt's partial work in an `except BaseException:` handler
     that re-raises. `BaseException`, not `Exception`, or an interrupt strands
     your own work while every plugin before you unwinds. A failure handler, not
     `finally`, because the cleanup is conditional on failing: `finally` needs a
     flag that every early `return` must set, and a missed one releases what a
     successful preparation just built. The bare `raise` keeps the wide catch
     clear of blind-except lint.
   - The two paths differ in lock state, so a single shared helper cannot serve
     both. Inside `prepare_call()` that callback's leases are still held;
     by `prepare_failed()` the callback was deactivated and they were released.
     Keep the lease-acquiring entry point separate from the release, and call the
     release directly from `prepare_call()` — acquiring there raises a nested-lease
     `RuntimeError` that masks the real failure in the diagnostics every
     downstream plugin sees.
   - `after_call()` does not run when preparation fails, and `after_goal()` still
     does not run on an interrupt, so durable resources must stay recoverable by
     a later `destroy` or a replayed provisioning journal.
     `engulf-clab/tests/test_preparation_unwind.py` pins every one of these
     behaviors against the installed runtime.
6. Use `InvocationAPI` only during its active callback. Do not retain API, state,
   or lease handles on a plugin instance.
7. Emit operational diagnostics through callback-bound `api.logger`. Do not
   configure logging or print from a runtime plugin.
8. Acquire `api.lease()` or `api.leases()` around long-lived shared resources.
   Keep `StateStore.transaction()` blocks short and never hold one while running
   an external command.
9. Declare context reads/writes in code. Declare hard ordering dependencies in
   the distribution's `engulf.plugins.v1.dependency.<plugin_id>` entry-point
   group — Engulf 0.2 rejects `plugin_dependencies` set in code. Do not rely on
   priority alone when correctness requires another plugin.

The canonical workspace is the selected topology's directory. Calls without a
filesystem topology use the current directory. Persist workspace-owned state
against that identity so the same lab behaves consistently from another shell
directory.

Topology label and environment-variable prefixes are a fixed `ECLAB_*`
literal, the same across every edition — never derive them from callback
application metadata. This keeps labels portable: one written for any
edition works unchanged under any other, and users are not confused by
near-identical prefixes that mean the same thing. `help()` must render this
fixed prefix, not an edition-derived one.

Topology-local state directories (used by plugins like `engulf-clab-freeze`
and `engulf-clab-license-pool` to stage generated files beside a lab) are the
one thing that still derives from the nonempty `short_product_name`,
falling back to `product`, normalized to uppercase underscore-separated
text. Editions are expected to keep `short_product_name` at `"eclab"` so
this state converges on one shared directory when they are branding variants.
A superset executable that owns a distinct schema pipeline and generated skill
must instead use that normalized pipeline ID as `short_product_name`, so its
topology-local state and schema artifacts are intentionally separate. Keep this
split — fixed portable labels, but metadata-derived state and pipelines —
intentional rather than reusing one prefix for both.

## Adding or changing a plugin

Every new directory under `plugins/` requires:

- a self-contained `pyproject.toml` and `src/<import_package>/` tree;
- its own `README.md`, `AGENTS.md`, MIT `LICENSE`, and build script;
- for a runtime plugin distribution, a concise `README.md` that links to a
  complete `USAGE.md` and a contributor-oriented `CONTRIBUTING.md`. Contract,
  library, and meta distributions — `engulf-clab-schema-api`,
  `engulf-clab-containers-api`, `engulf-clab-ensure-checkout`, and
  `engulf-clab-all-plugins` — keep a single reference `README.md` instead,
  because their README is the API reference rather than an operator guide;
- `py.typed` when the package exposes typed Python interfaces;
- compatible `engulf-api>=1.2,<2` and
  `engulf-executable-wrapper-api>=1.2,<2` dependencies for runtime plugins;
- both required entry-point declarations for a discoverable plugin, plus a
  dependency entry-point group when the plugin needs a hard ordering edge;
- a dependency in `engulf-clab-all-plugins` when it is part of the maintained
  default catalog; and
- unit tests that isolate Docker, Git, QEMU, host networking, and other external
  effects.

Use `Copyright (c) 2026 Karel Chanivecky` in a new plugin's MIT license. Plugin
IDs are lowercase, dot-qualified identifiers such as `engulf_clab.example`.

When topology mutation is required, depend on `engulf-clab-lab-parser`, record
deferred operations with an editor owned by the plugin ID, and depend on
`engulf-clab-lab-writer`. Never edit the selected YAML in place. Mutators and
graph contributors must run before the image dispatcher; collectors must run
after every mutator and dispatcher. Concrete providers depend on the neutral
image contract, never on another provider.

## Documentation contract

Documentation has complementary authorities:

| Surface | Audience | Required content |
| --- | --- | --- |
| Runtime plugin `README.md` | Package index readers | Concise purpose and links to usage and contribution guides |
| Contract/library `README.md` | Plugin authors | Complete API reference for a non-runtime distribution |
| Distribution `USAGE.md` | Users and operators | Installation, prerequisites, configuration, examples, lifecycle, cleanup, security, and troubleshooting |
| Distribution `CONTRIBUTING.md` | Human contributors | Package role, architecture, invariants, ordering/context contracts, and validation commands |
| Nearest `AGENTS.md` | Coding agents | Repository instructions, prohibited behavior, and contributor-contract pointers |
| Plugin `help()` | Users of the installed runtime | Installed feature marker, exact active prefix, concise option syntax, and the next discovery command |
| Source, types, and tests | Maintainers | Precise behavior and executable edge-case specification |

For every behavior change, review all surfaces. A plugin `USAGE.md` should
state at least:

- what installs and activates the feature;
- whether it applies to deploy, destroy, help, or every wrapped command;
- every topology field, label, command option, and invocation variable;
- how relative paths and the fixed label / state-directory prefixes are resolved;
- required host tools and privileges;
- temporary files, user/workspace state, leases, and cleanup behavior;
- concurrency, idempotency, and failure semantics; and
- a safe validation or troubleshooting sequence.

Prefer links to authoritative upstream specifications over copied prose. Keep
examples generic unless the package is intentionally product-specific. Never
put credentials, license contents, private paths, or profile secrets in an
example.

## Runtime schema and skill

Each feature plugin owns an import-time `PluginSchema` builder and records its
immutable snapshot during `before_goal`. The generator runs last and composes
those snapshots with the exact selected Containerlab schema. Detailed references
come from packaged `USAGE.md` resources, not repository mirrors. Contributor-only
`CONTRIBUTING.md` and `AGENTS.md` resources must not be embedded in generated lab
skills.
Executable-wrapper contributors should derive from `SchemaBackedPlugin`; it
turns command/flag/value declarations into Bash, Zsh, and Fish completion and
normalizes explicitly environment-backed global flags before outer callbacks.
Keep node `env` declarations distinct from wrapper-consumed runtime defaults.
Environment values support persistent configuration; matching CLI flags are
per-invocation overrides and take precedence.

After changing a declaration, referenced document, compiler, or skill template,
run `make check-skill`. Keep every option explanation to one line and at most
240 characters. The generated `SKILL.md` stays procedural and concise; detailed
package contracts and the composed JSON Schema live under fingerprinted
references.

## Validation

Run the narrowest checks that exercise the changed boundary. Common commands
from an installed development environment are:

```bash
.venv/bin/python -m compileall -q engulf-clab/src mcp-server/src plugins
.venv/bin/python -m pytest -q plugins/engulf-clab-containers/tests
.venv/bin/python -m pytest -q mcp-server/tests
.venv/bin/eclab --help
.venv/bin/eclab --engulf-plugin-list
.venv/bin/eclab --eclab-containers-help
make check-skill
git diff --check
```

Run a package's own tests after changing it and the tests of direct consumers
after changing a shared API. In particular:

- container API changes require manager and core collection tests;
- image API/core changes require dispatcher, Dockerfile adapter, and provider tests;
- parser changes require every topology mutator and writer tests;
- checkout helper changes require both ensure-plugin test suites;
- wrapper/Engulf changes require plugin discovery and dynamic-help checks; and
- MCP security/configuration changes require the complete MCP suite.

Use `make build` for a release-level build of every distribution and Twine
metadata validation. It recreates root `dist/`; do not commit build artifacts.
Do not run real deploy/destroy, Docker builds, network mutation, Git clones, or
privileged MCP installation unless the task explicitly requires them.

## Commits and release preparation

Commits that change wrapper, plugin, MCP, schema, skill, or related documentation
need exactly one review trailer:

```text
Skill-Impact: updated
```

Use `Skill-Impact: updated` when runtime declarations, compiler output, or the
generated skill contract changes. Use `none` only after reviewing the impact.

Keep commits focused. Before releasing, update each changed distribution's
version and compatible dependency range together, build all artifacts with
`make build`, and inspect the wheel contents. Artifact publication is handled by
external release tooling rather than scripts in this repository.
