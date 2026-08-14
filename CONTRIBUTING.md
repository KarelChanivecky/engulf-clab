# Contributing to engulf-clab

This monorepo releases the `eclab` wrapper, a local privileged MCP service,
independent Engulf plugin distributions, and the packaged `develop-eclab-lab`
Codex skill. A change is complete only when its behavior, runtime help,
user-facing README, contributor guidance, and bundled skill snapshot agree.

## Contents

- [Repository model](#repository-model)
- [Development environment](#development-environment)
- [Engulf plugin contract](#engulf-plugin-contract)
- [Adding or changing a plugin](#adding-or-changing-a-plugin)
- [Documentation contract](#documentation-contract)
- [Skill synchronization](#skill-synchronization)
- [Validation](#validation)
- [Commits and releases](#commits-and-releases)

## Repository model

| Path | Responsibility | Release unit |
| --- | --- | --- |
| `engulf-clab/` | Defines the `eclab` application and wraps Containerlab. | `engulf-clab` |
| `plugins/<distribution>/` | Implements one feature or shared typed contract. | One Python distribution per directory |
| `mcp-server/` | Provides the stdio bridge, privileged daemon, installer, and systemd unit. | `engulf-clab-mcp` |
| `skills/develop-eclab-lab/` | Holds the canonical skill, embedded references, and pip installer. | `develop-eclab-lab` |
| `scripts/` and `.githooks/` | Synchronize and validate the skill and commit metadata. | Repository tooling only |

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
5. Use `InvocationAPI` only during its active callback. Do not retain API, state,
   or lease handles on a plugin instance.
6. Emit operational diagnostics through callback-bound `api.logger`. Do not
   configure logging or print from a runtime plugin.
7. Acquire `api.lease()` or `api.leases()` around long-lived shared resources.
   Keep `StateStore.transaction()` blocks short and never hold one while running
   an external command.
8. Declare context reads/writes and hard ordering dependencies. Do not rely on
   priority alone when correctness requires another plugin.

The canonical workspace is the selected topology's directory. Calls without a
filesystem topology use the current directory. Persist workspace-owned state
against that identity so the same lab behaves consistently from another shell
directory.

Application-facing configuration prefixes come from the nonempty
`short_product_name`, falling back to `product`; normalize to uppercase,
underscore-separated text. Base eclab therefore uses `ECLAB_*`, while an
edition can use another prefix. Dynamic `help()` must render the active prefix
from callback metadata rather than hard-code an edition assumption.

## Adding or changing a plugin

Every new directory under `plugins/` requires:

- a self-contained `pyproject.toml` and `src/<import_package>/` tree;
- its own `README.md`, `AGENTS.md`, MIT `LICENSE`, and build script;
- `py.typed` when the package exposes typed Python interfaces;
- compatible `engulf-api>=1.0,<2` and
  `engulf-executable-wrapper-api>=1.0,<2` dependencies for runtime plugins;
- both required entry-point declarations for a discoverable plugin;
- a dependency in `engulf-clab-all-plugins` when it is part of the maintained
  default catalog; and
- unit tests that isolate Docker, Git, QEMU, host networking, and other external
  effects.

Use `Copyright (c) 2026 Karel Chanivecky` in a new plugin's MIT license. Plugin
IDs are lowercase, dot-qualified identifiers such as `engulf_clab.example`.

When topology mutation is required, depend on `engulf-clab-lab-parser`, record
deferred operations with an editor owned by the plugin ID, and depend on
`engulf-clab-lab-writer`. Never edit the selected YAML in place. Mutators that
produce Dockerfile recipes must run before the Dockerfile builder; collectors
must run after every mutator.

## Documentation contract

Documentation has four complementary authorities:

| Surface | Audience | Required content |
| --- | --- | --- |
| Root and distribution `README.md` files | Users and operators | Installation, prerequisites, configuration, examples, lifecycle, cleanup, security, and troubleshooting |
| Nearest `AGENTS.md` | Coding agents and contributors | Package role, invariants, ordering/context contracts, prohibited behavior, and validation commands |
| Plugin `help()` | Users of the installed runtime | Installed feature marker, exact active prefix, concise option syntax, and the next discovery command |
| Source, types, and tests | Maintainers | Precise behavior and executable edge-case specification |

For every behavior change, review all four surfaces. A plugin README should
state at least:

- what installs and activates the feature;
- whether it applies to deploy, destroy, help, or every wrapped command;
- every topology field, label, command option, and invocation variable;
- how relative paths and edition prefixes are resolved;
- required host tools and privileges;
- temporary files, user/workspace state, leases, and cleanup behavior;
- concurrency, idempotency, and failure semantics; and
- a safe validation or troubleshooting sequence.

Prefer links to authoritative upstream specifications over copied prose. Keep
examples generic unless the package is intentionally product-specific. Never
put credentials, license contents, private paths, or profile secrets in an
example.

## Skill synchronization

The canonical skill lives in `skills/develop-eclab-lab`; installed copies are
outputs, not sources. Its references are normalized snapshots of this monorepo
and the neighboring Engulf repository. Read `skills/README.md` for the complete
maintenance, packaging, installation, hook, and release workflow.

After changing a mirrored README or `AGENTS.md`, synchronize and validate:

```bash
ENGULF_DIR=../cliwrap make update-skill
ENGULF_DIR=../cliwrap make check-skill
```

Do not edit generated reference snapshots independently. Add a source mapping
or a documented normalization when new authoritative context is required. Keep
`SKILL.md` procedural and concise; put detailed package contracts in
`references/` so an agent loads them only when relevant.

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
ENGULF_DIR=../cliwrap make check-skill
git diff --check
```

Run a package's own tests after changing it and the tests of direct consumers
after changing a shared API. In particular:

- container API changes require manager and core collection tests;
- parser changes require every topology mutator and writer tests;
- checkout helper changes require both ensure-plugin test suites;
- wrapper/Engulf changes require plugin discovery and dynamic-help checks; and
- MCP security/configuration changes require the complete MCP suite.

Use `make build` for a release-level build of every distribution and Twine
metadata validation. It recreates root `dist/`; do not commit build artifacts.
Do not run real deploy/destroy, Docker builds, network mutation, Git clones, or
privileged MCP installation unless the task explicitly requires them.

## Commits and releases

Repository hooks are installed by `make install-skill`. The pre-commit hook
checks staged source/reference parity and rejects vendor-specific content in the
generic skill. The commit-message hook requires exactly one trailer when a
wrapper, plugin, MCP, or mirrored documentation change may affect the skill:

```text
Skill-Impact: updated
```

Use `Skill-Impact: none` only after reviewing the skill and determining that no
instruction or bundled reference changes. An `updated` commit must stage a
change under `skills/develop-eclab-lab/`.

Keep commits focused. Before releasing, update each changed distribution's
version and compatible dependency range together, build all artifacts with
`make build`, inspect the wheel contents, and publish only freshly built output.
`TWINE_REPOSITORY_URL` selects the package index; `publish.sh` can obtain local
managed-repository credentials from the neighboring Engulf checkout.
