# Agent Guide

This file applies to the whole workspace. Read the README owned by the subsystem
before editing it. Do not infer contracts from the removed `Engulf`, `BinaryWrapper`,
`before_call`, or edit-capability APIs.

## Package Boundaries

| Distribution | Import | Owns |
| --- | --- | --- |
| `engulf-api` | `engulf_api` | Stable goal, plugin, lifecycle, logging, and state interfaces |
| `engulf` | `engulf` | `Application`, discovery, ordering, diagnostics, state, locks, and dispatch |
| `engulf-executable-wrapper-api` | `engulf_executable_wrapper_api` | Wrapper events, contributions, registries, and plugin adapter |
| `engulf-executable-wrapper` | `engulf_executable_wrapper` | Executable goal, process runner, help, and completion |
| `engulf-plugin-list` | `engulf_plugin_list` | Isolated executable-wrapper plugin inventory diagnostic |

Dependency direction is one-way:

```text
engulf-api <- engulf <- engulf-executable-wrapper
     ^                       ^
     `-- engulf-executable-wrapper-api --'
```

- `engulf-api` remains dependency-free and never imports a runtime package.
- Generic framework code must not import executable-wrapper packages.
- `engulf-api`, `engulf`, and goal API packages remain OS-independent. Keep POSIX
  imports in `engulf._state_posix` and Windows API use in `engulf._state_windows`.
- `engulf-executable-wrapper` is intentionally Linux-specific; do not let its signal,
  process-group, or shell-completion assumptions leak into core.
- Goal plugin wheels depend on `engulf-api` and their goal-specific API package, not
  the runtime implementation.
- Every public package is typed and includes `py.typed`.

Do not bump existing versions while the first release is under development.
`PLUGIN_API_MAJOR` remains 1. New goal API packages independently declare their goal
major.

## Developing An Application

Every application owns exactly one goal:

```python
from engulf import ApplicationDefinition, PluginPolicy

APPLICATION = ApplicationDefinition(
    application_id="com.example.app",
    display_name="example-app",
    goal_factory=MyGoal,
    vendor="Example Corp",
    product="Example App",
    short_product_name="Example",
    version="1.0.0",
    plugin_policy=PluginPolicy.declared(),
)
```

Export definitions from side-effect-free core modules. Console launchers create and
close a fresh `Application`; importing an app core must not discover plugins or run
goal setup. Use direct `Application` construction only as the lower-level runtime
API.

Treat `application_id` as persistent compatibility and state metadata. Changing it
changes application entry-point discovery, state location, and lease identity.
`display_name` controls diagnostics and reserved logging option names.
Every callback receives immutable `api.application` metadata containing technical
`application_id` and descriptive `display_name`, `vendor`, `product`,
`short_product_name`, and `version`.
Plugins may derive presentation or external naming conventions from the descriptive
fields, but must never use them for compatibility, state, leases, elevation, trust,
or authorization.

Use `definition.edition()` for a differently branded launcher representing the same
logical application. Editions retain the application ID and therefore share plugin
declarations, state, leases, and future app-scoped policy. They may add optional or
required plugins and override display/vendor/product/version while inheriting any
omitted metadata, but do not remove base selections. `PluginPolicy.including()` may
unblock a base blocklist entry; blocklists are activation defaults, not security
deny lists.

Use `definition.fork()` for an independent product. A fork gets a new application
ID, state tree, and lease namespace. Application declaration inheritance is off by
default and must be requested explicitly with `inherit_declarations=True`; inherited
declarations affect selection only and never grant trust. Goals intended for
editions obtain command-facing names from `GoalSetupAPI.display_name`.

Package reusable app behavior as a script-free core wheel. Official and vendor
launcher wheels depend on it and expose separate console scripts. Vendor-only plugin
wheels publish the goal catalog entry and are explicitly included by the vendor
edition; they should not declare the shared application ID unless the official
launcher should also activate them.

Select installed plugins deliberately:

- `PluginPolicy.declared(include=...)`: union plugin-side app declarations with IDs
  drawn in by the application.
- `PluginPolicy.allow_only(...)`: ignore plugin-side declarations and activate only
  named IDs. Dependencies must also be named unless `include_dependencies=True`,
  which recursively activates reachable `PluginDependency` targets.
- `PluginPolicy.allow_all_except(...)`: activate every current-goal catalog entry
  except blocked IDs.

Explicit IDs are optional when absent. Dependencies reached from an active plugin
are never optional, including when implicit dependency activation is enabled.
Use `required_plugin_ids` or `require_plugins` when an application cannot operate
without a selected plugin; missing required IDs fail construction before goal setup.
Do not use application policy to bypass goal ID, goal API major, or plugin runtime
type checks.

Use `plugin_dir` only for application-owned or development plugins. Installed wheels
must use entry points.

Close long-lived applications during shutdown or use `Application` as a context
manager. `Application.active_plugins` and `Application.plugins` expose immutable
`ActivePlugin` descriptors; application code must not reach into live plugin
instances. Treat `PluginSource` as observed provenance and `PluginMetadata` as a
plugin declaration. Do not conflate either with a trust decision. One application
supports repeated but not overlapping invocations, and it cannot close while an
invocation is active.

## Developing A Goal

A goal defines an invocation's outcome and process. Implement:

- stable `GoalContract(GoalRequirement(goal_id, api_major), plugin_type)`;
- optional one-time `setup(GoalSetupAPI)`;
- per-invocation `achieve(Invocation, GoalAPI) -> GoalResult[T]`.

Goal commands or modes remain internal to one goal. Do not create a separate goal per
subcommand unless the application truly has different invocation outcomes.

Dispatch goal-specific plugin callbacks through immutable `GoalPhase` values. Every
phase selects one shared `PluginOrder`: preprocessing or postprocessing. Return
immutable contributions and let the goal merge them only after dispatch completes.
Plugins must not observe other plugins' contributions during their callback.

Construct phases with keyword arguments. `phase_id` is the stable dispatch and
future transport identity; `local_callback` is only the in-process adapter. Keep
that adapter module-level and limited to forwarding into the goal-specific plugin
contract. Do not place goal logic or captured invocation state in it. Prefer frozen,
explicitly typed events and contributions so a later goal-owned codec can transport
them without changing the phase contract. Mutable registries and arbitrary callables
are inherently local-only unless the goal later defines a separate remote form.

The goal receives managed diagnostics, context, state, transactions, leases, and
workspaces under a reserved goal namespace. Do not bypass these facilities with
ad-hoc global storage or lock files.

Goal exceptions and invalid phase returns become framework failures. Preserve stable
plugin IDs in diagnostics and attributed results.

## Developing A Plugin

Every adapter derives from the goal's plugin type and declares one globally unique,
lowercase, dot-qualified `plugin_id`. Base priority is 50. Declare privilege use with
`ElevationRequirement.NONE`, `OPTIONAL`, or `REQUIRED`; never probe or elevate at
module import time. Required elevation fails application construction before setup,
while optional plugins must branch on callback-bound `api.elevated` and provide a
coherent unprivileged path.

The inherited `Plugin.metadata` property creates the immutable metadata snapshot.
Keep declarations side-effect free and do not override `metadata` to inspect the
machine, application, or invocation. Runtime compatibility may eventually obtain
the same value outside the application process.

Installed metadata requires a goal catalog entry whose name equals `plugin_id`:

```toml
[project.entry-points."engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper"]
"com.example.plugin" = "example_plugin:plugin"
```

Plugin-side consent for an application repeats the same ID and target:

```toml
[project.entry-points."engulf.plugins.v1.application.com_example_app"]
"com.example.plugin" = "example_plugin:plugin"
```

Repeat the application table for every application supported by one implementation.
An application may activate the goal-catalog entry without this second declaration.
A package spanning unrelated goals exports separate adapters under each goal catalog;
do not add wildcard goal compatibility.

Wheel dependencies make code installable. `PluginDependency` separately requires an
adapter to be active and defines independent preprocess/postprocess ordering. Neither
mechanism replaces the other.

Use callback `api.logger`; do not attach handlers or change logger levels. Registration
logging is available after activation because unselected catalog modules are never
imported. Retained loggers and APIs must fail outside their callback.

Normal goal plugins execute in-process with the application's full OS authority.
`PluginPolicy` selects code and `ElevationRequirement` reports compatibility; neither
establishes trust or isolation. Never describe plugin state directories as an OS
sandbox. Elevated applications must activate only trusted packages from trusted,
non-user-writable Python and plugin locations.

Diagnostic extensions are a distinct import-free discovery kind and are never
normal goal plugins. Their targets run only in bounded Linux Bubblewrap workers
after namespace, mount, resource, and seccomp isolation succeeds. They receive only
sanitized request/record data over bounded JSON. If isolation is unavailable, keep
targets unimported, warn once, and reject declared diagnostic triggers with framework
exit 70 while leaving ordinary invocations unchanged.

## Executable-Wrapper Plugins

Derive from `ExecutableWrapperPlugin` and keep phases distinct:

- `analyze_call`: side-effect free; return immutable removals, additions, and optional
  preemption after inspecting original arguments.
- `prepare_call`: perform viable external work only after all vetoes resolve.
- `after_call`: finalize in postprocessing order using the complete outcome.

All analyzers see the same original call. Added arguments are hidden until merge.
Preemption never prevents another analyzer from running, but it prevents every
preparer from running. Use `preempted_by` as a stable plugin ID.

Keep process execution shell-free, inherit standard streams, preserve controlling
terminal behavior, and keep the direct child in the wrapper's process group. Forward
temporary wrapper-PID signals to the child and restore inherited handlers before
postprocessing. Preserve exits 127, 126, `128 + signal`, and framework 70.

Completion and help belong to the executable-wrapper goal packages, not core.
Argument registration is completion metadata only; runtime edits come from returned
`CallContribution` values.

## Context, State, And Locks

Context lives for one `Application.invoke()` and is shared across entered lifecycle
hooks and goal phases. Declare exact `context_reads` and `context_writes`. Context
metadata does not imply dependency ordering.

Use workspace state for deploy/destroy data tied to a canonical workspace. Use user
state for application-global plugin data and `known_workspaces()` for global cleanup
operations such as destroy-all.

State invariants:

- filename APIs accept one path component and preserve link/reparse, owner-private,
  and atomic-write protections;
- `directory` is the API-namespaced filesystem view for trees such as cloned repositories;
- reads use shared store locks; directory/path/write/delete operations use exclusive
  locks;
- atomic writes do not make read-modify-write atomic;
- transactions serialize and do not roll back completed writes;
- workspace destruction is deferred, takes the store lock, and prunes empty records;
- queued cleanup is attempted for every participant even after failures.

Lease invariants:

- acquire all external-resource leases before state transactions;
- lease identity includes state owner/home, application ID, and exact name, but not
  plugin ID;
- multi-lease acquisition validates first, deduplicates, sorts, uses one deadline,
  releases partial acquisition on failure, and releases in reverse order;
- lock files remain persistent and non-inheritable; POSIX uses mode 0600 and
  no-follow, while Windows uses protected DACLs and open-reparse-point checks;
- callback deactivation and API close forcibly release leaked lock contexts.

Leases coordinate cooperating Engulf processes only. Keep ownership markers and
recovery journals for bridges, processes, images, firewall rules, and other external
resources.

## Contributing

Keep edits in the owning package. Generic lifecycle changes require contract tests in
`engulf-api` and runtime tests in `engulf`. Wrapper behavior requires corresponding
API/runtime tests in its two packages.

Keep `Application` responsible for discovery, diagnostics sessions, invocation
resources, goal execution, and cleanup. Hook traversal and goal-phase dispatch belong
in `engulf._dispatch`. Keep `RuntimePluginAPI` as the public runtime facade;
activation, context access, state handles, and lock coordination belong to the
collaborators in `engulf._capabilities`.

All plugin calls in dispatch must go through the internal execution endpoint. Do not
restore direct `LoadedPlugin` implementation access in `_dispatch`, and do not expose
live implementations through public application inspection. Endpoint cleanup must
remain idempotent and be attempted on application close and construction failure.
Future trust or process-isolation work belongs behind this seam and must not change
the meaning of existing activation policy.

Before completion, run:

```console
python3.14 -m venv --upgrade-deps .venv
.venv/bin/python -m pip install --group dev
PYTHONPATH=engulf-api/src .venv/bin/python -m unittest discover -s engulf-api/tests -v
PYTHONPATH=engulf-api/src:engulf-executable-wrapper-api/src .venv/bin/python -m unittest discover -s engulf-executable-wrapper-api/tests -v
PYTHONPATH=engulf-api/src:engulf/src .venv/bin/python -m unittest discover -s engulf/tests -v
PYTHONPATH=engulf-api/src:engulf/src:engulf-executable-wrapper-api/src:engulf-executable-wrapper/src .venv/bin/python -m unittest discover -s engulf-executable-wrapper/tests -v
.venv/bin/python -m ruff check engulf-api engulf engulf-executable-wrapper-api engulf-executable-wrapper plugins examples
.venv/bin/python -m ruff format --check engulf-api engulf engulf-executable-wrapper-api engulf-executable-wrapper plugins examples
.venv/bin/python -m mypy
```

When package metadata changes, build all five wheels and source distributions and run
Twine checks. Do not hand-edit generated archives or publish unless explicitly asked.

Use deterministic subprocess/multiprocessing coordination for lock and signal tests.
Cover failure, ordering, repeated invocation, policy filtering, and non-import of
unselected plugins, not only successful paths.
