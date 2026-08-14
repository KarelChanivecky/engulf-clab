# engulf-executable-wrapper-api

This package defines the goal-specific plugin contract for
`org.engulf.executable-wrapper` API major 1. It depends only on `engulf-api`; plugin
wheels should not import runtime implementation modules from `engulf` or
`engulf-executable-wrapper`.

The contract package is OS-independent and can be imported by plugin tooling on any
supported Python platform. The current `engulf-executable-wrapper` goal runtime is
Linux-specific.

Import public contracts from `engulf_executable_wrapper_api`. The fixed contract
constants are:

| Constant | Value |
| --- | --- |
| `EXECUTABLE_WRAPPER_GOAL_ID` | `"org.engulf.executable-wrapper"` |
| `EXECUTABLE_WRAPPER_API_MAJOR` | `1` |
| `EXECUTABLE_WRAPPER_API_VERSION` | `"1.0.0"` |

Plugins that manipulate privileged external resources declare their elevation
behavior through the generic Engulf contract:

```python
from engulf_api import ElevationRequirement


class NetworkPlugin(ExecutableWrapperPlugin):
    plugin_id = "com.example.network"
    elevation_requirement = ElevationRequirement.REQUIRED
```

Use `OPTIONAL` when the plugin has a complete unprivileged path, and inspect
`api.elevated` inside registration or invocation callbacks. Engulf validates
`REQUIRED` before registration but does not run `sudo` or request elevation itself.
This declaration is not authorization: the current runtime executes every selected
wrapper plugin in-process, so every plugin has the wrapper application's authority.

## Complete Plugin Example

```python
from engulf_api import InvocationAPI, RegistrationAPI
from engulf_executable_wrapper_api import (
    AdditionPlacement,
    AfterCallEvent,
    ArgumentAddition,
    BeforeCallEvent,
    CallContribution,
    ExecutableWrapperPlugin,
    PreparedCallEvent,
)


class AuditPlugin(ExecutableWrapperPlugin):
    plugin_id = "com.example.shared.audit"
    priority = 50

    def register_arguments(self, registry, api: RegistrationAPI) -> None:
        registry.option(
            "--audit-label",
            takes_value=True,
            description="Attach an audit label",
        )
        api.logger.debug(
            "registered audit metadata for %s %s",
            api.application.vendor,
            api.application.product,
        )

    def register_completions(self, registry, api: RegistrationAPI) -> None:
        registry.candidate("--audit-summary")

    def help(self, api) -> str:
        return "  --audit-label LABEL   Attach an audit label"

    def analyze_call(
        self,
        event: BeforeCallEvent,
        api: InvocationAPI,
    ) -> CallContribution | None:
        removals: set[int] = set()
        additions: list[ArgumentAddition] = []

        for index, argument in enumerate(event.wrapper_args):
            if argument == "--audit-summary":
                removals.add(index)
                additions.append(
                    ArgumentAddition(
                        ("--summary",),
                        AdditionPlacement.BEFORE_SEPARATOR,
                    )
                )

        if not removals and not additions:
            return None
        return CallContribution(
            removals=frozenset(removals),
            additions=tuple(additions),
        )

    def prepare_call(
        self,
        event: PreparedCallEvent,
        api: InvocationAPI,
    ) -> None:
        api.logger.info(
            "calling executable with %d arguments", len(event.effective_args)
        )

    def after_call(
        self,
        event: AfterCallEvent,
        api: InvocationAPI,
    ) -> None:
        api.logger.info("executable exited %d", event.outcome.exit_code)


plugin = AuditPlugin()
```

`ExecutableWrapperPlugin` supplies the correct `GoalRequirement`; subclasses do not
repeat the goal ID or major.

## Immutable Call Model

All call-phase callbacks receive frozen event values. `wrapper_args` always means
the original arguments after Engulf has removed its own logging controls. Added or
removed arguments never leak back into another analyzer.

| Event | Fields and timing |
| --- | --- |
| `BeforeCallEvent` | `binary`, original `wrapper_args`, and `mode`; sent to every analyzer. |
| `PreparedCallEvent` | `binary`, original `wrapper_args`, merged `effective_args`, and `mode`; sent only for viable normal execution. |
| `AfterCallEvent` | Both argument tuples, mode, final `CallOutcome`, and monotonic `duration_seconds`; sent after preemption or an execution attempt. |

`CallMode.NORMAL` is ordinary execution. `CallMode.HELP` is selected only by an
exact `--help` argument. Help-like values such as `--help=topic` remain normal.

`CallOutcome` exposes `kind`, `exit_code`, and `process_started`, with optional
`signal`, stable `preempted_by` plugin ID, and `error` text:

| `OutcomeKind` | Runtime meaning |
| --- | --- |
| `COMPLETED` | The child exited normally, including with a nonzero domain exit. |
| `PREEMPTED` | A plugin selected an exit without starting the child. |
| `SPAWN_FAILED` | The executable could not be resolved or invoked. |
| `SIGNALED` | The started child terminated from a signal. |
| `FRAMEWORK_FAILED` | Contract representation for framework failure; current phase failures normally become an outer framework-failed `GoalResult` before an after-call event can be created. |

Every outcome exit is an exact integer from 0 through 255. The goal runtime maps
not-found to 127, other spawn errors to 126, and signals to at most
`128 + signal` (capped at 255).

## Contribution Model

`CallContribution` contains a `frozenset` of zero-based original argument indexes to
remove, a tuple of `ArgumentAddition` groups, and an optional
`preempt_exit_code`. Each addition group is atomic and contains a nonempty tuple of
NUL-free strings.

| `AdditionPlacement` | Position in the merged call |
| --- | --- |
| `PREPEND` | Before every surviving original argument. |
| `BEFORE_SEPARATOR` | Immediately before the first surviving `--`, or at the end when no separator survives. This is the default. |
| `APPEND` | After every surviving original argument, including after `--`. |

Removals apply only to the original tuple; they never index added values. An
out-of-range removal is a plugin-attributed framework failure. Identical added
argument tuples are coalesced across contributions, retaining the first placement;
they are not coalesced against identical original arguments. Distinct groups keep
phase execution order and each contribution's tuple order within their placement.

## Phase Semantics

### `analyze_call`

Every active plugin sees the same immutable original `BeforeCallEvent`. Analyze the
call and return an immutable `CallContribution`. Treat this phase as side-effect
free. Other plugins cannot see your returned edits or preemption while analyzing.

After all analyses:

- removals from every plugin are unioned;
- identical added argument tuples are coalesced, with the first placement retained;
- different tuples remain distinct and preserve activation order;
- removals apply only to original argument indexes;
- the first nonzero preemption in preprocessing order wins;
- nonzero preemptions precede zero; the first zero wins only when no nonzero exists.

Help mode still calls every analyzer but ignores argument edits and preemption.

### `prepare_call`

Preparation runs only after all contributions are validated and only when the call
was not preempted. Help mode skips preparation. Put long-running or external side
effects here, not in analysis.

Use named leases before manipulating shared resources, followed by short state
transactions:

```python
with api.leases(
    (
        f"docker-image:{image}",
        f"vrnetlab-builder:{builder.resolve()}",
    )
):
    inspect_or_build()
    with state.transaction() as locked:
        reread_merge_and_save(locked)
```

### `after_call`

Finalization uses postprocessing order and receives original/effective arguments,
duration, and a `CallOutcome`. The outcome identifies preemption with the stable
`plugin_id` in `preempted_by`.

Callback exceptions stop the current goal phase and produce framework exit code 70.
Lifecycle cleanup still releases callback-bound locks and processes requested state
destruction.

## Packaging A Reusable Plugin

Use a normal wheel with both the goal catalog entry and any plugin-side application
declarations:

```toml
[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"

[project]
name = "example-engulf-audit"
version = "0.1.0"
requires-python = ">=3.14"
dependencies = [
    "engulf-api>=1.0,<2",
    "engulf-executable-wrapper-api>=1.0,<2",
]

[project.entry-points."engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper"]
"com.example.shared.audit" = "example_audit:plugin"

[project.entry-points."engulf.plugins.v1.application.com_example_first"]
"com.example.shared.audit" = "example_audit:plugin"

[project.entry-points."engulf.plugins.v1.application.com_example_second"]
"com.example.shared.audit" = "example_audit:plugin"

[tool.hatch.build.targets.wheel]
packages = ["src/example_audit"]
```

The goal catalog is the technical compatibility declaration. Each application group
is plugin-side activation consent. The entry-point name must exactly equal
`plugin.plugin_id`, and every declaration must use the same distribution and target.

The same implementation can therefore activate for any number of executable-wrapper
applications. It does not need to depend on those applications unless it imports
their private contracts.

An application can draw in a cataloged plugin even without an application-group
entry:

```python
PluginPolicy.declared(include={"com.example.shared.audit"})
```

Allowlist and blocklist policy are documented in `engulf/README.md`. Missing explicit
IDs are optional, but a selected plugin's `PluginDependency` values must all be
active. An allowlist can opt into recursive activation of those dependencies with
`PluginPolicy.allow_only(ids, include_dependencies=True)`.

## Plugins Supporting Different Goals

One package may support several goal contracts, but it should export a separate
adapter object under each goal catalog. Each adapter derives from that goal's plugin
type and declares that goal's requirement. Do not use wildcard goal compatibility.

## Completion Metadata

`register_arguments()` and `register_completions()` run once during goal setup with
initialized loggers. Argument declarations affect wrapper completion only; they do
not parse, validate, consume, or automatically remove runtime arguments. Runtime
argument behavior comes exclusively from returned `CallContribution` values.

Register option metadata with every spelling in one call:

```python
def register_arguments(self, registry, api) -> None:
    registry.option(
        "-p",
        "--profile",
        takes_value=True,
        metavar="NAME",
        description="Select a profile",
        value_completer=lambda context: ["dev", "staging", "production"],
        visible_to_binary_completion=False,
        repeatable=False,
    )
```

`ArgumentRegistry.option()` returns an immutable `OptionSpec`. Names must begin with
`-` and must not collide with any earlier registration. A `value_completer` requires
`takes_value=True`. Before `--`, an option hidden from binary completion also hides
its separate value; set `visible_to_binary_completion=True` only when the wrapped
executable's native completer should see it. `repeatable=False` suppresses an option
candidate after any spelling has already appeared. These flags still have no
runtime parsing effect.

The resulting fields are `names`, `takes_value`, `metavar`, `description`,
`value_completer`, `visible_to_binary_completion`, and `repeatable`.

`ArgumentRegistry.options` returns registrations in insertion order.
`find_exact(word)` and `find_assignment(word)` are available to goal/completion
tooling that needs to resolve registered metadata without reimplementing spelling
rules.

Register literal and dynamic top-level candidates separately:

```python
from engulf_executable_wrapper_api import CompletionCandidate


def complete_targets(context):
    return [
        CompletionCandidate("server-a", "Primary server"),
        "server-b",
    ]


def register_completions(self, registry, api) -> None:
    registry.candidate(
        "--audit-summary",
        description="Print an audit summary",
        when=lambda context: "--quiet" not in context.words,
    )
    registry.provider(complete_targets)
```

A provider may be a `CompletionCallable` or an object satisfying the runtime-checkable
`CompletionProvider.complete()` protocol. It yields `CandidateLike` values: strings
or `CompletionCandidate(value, description=None)`. Candidate values must be nonempty
and NUL-free. `normalize_candidate()` converts either form, and `invoke_provider()`
calls either provider style.

`CompletionRegistry.providers` returns dynamic providers in registration order, and
`static_candidates(context)` evaluates predicates and returns matching literal
candidates for that context.

`CompletionContext` contains `shell` (`Shell.BASH` or `Shell.ZSH`), the invoked
`wrapper_command`, configured `binary`, argument `words` excluding the wrapper
command, and the argument-relative `cursor_index`. Its `current` property safely
returns the word being completed or `""`; `previous` returns the preceding word or
`None`. Predicates and providers should be deterministic and should filter or
generate candidates from this immutable context.

At runtime, option-value candidates support both a separate value and
`--option=value`. Literal candidates are prefix-filtered. Candidates from the
application's optional binary provider, argument registry, static registry, and
dynamic providers are merged in that order and deduplicated by value; the first
description is retained unless a later duplicate supplies the first nonempty one.
The application binary provider is consulted only when native executable completion
was not found.

These registration APIs intentionally accept mutable registries and Python
completion callables, so they are local-execution contracts. A future isolated
execution mode would need a separate declarative registration representation; do
not serialize or persist registry/provider objects yourself.

`help(api: HelpAPI)` is also collected during setup. `HelpAPI` exposes only
immutable application metadata and a configured logger. Return an empty string for
no section; the runtime strips trailing line endings and attributes every nonempty
block to the stable plugin ID.

## Public Import Surface

| Area | Names |
| --- | --- |
| Contract | `EXECUTABLE_WRAPPER_GOAL_ID`, `EXECUTABLE_WRAPPER_API_MAJOR`, `EXECUTABLE_WRAPPER_API_VERSION`, `ExecutableWrapperPlugin`, `HelpAPI` |
| Calls | `CallMode`, `BeforeCallEvent`, `PreparedCallEvent`, `AfterCallEvent`, `CallOutcome`, `OutcomeKind` |
| Contributions | `CallContribution`, `ArgumentAddition`, `AdditionPlacement` |
| Argument metadata | `ArgumentRegistry`, `OptionSpec` |
| Completion | `Shell`, `CompletionContext`, `CompletionCandidate`, `CandidateLike`, `CompletionPredicate`, `CompletionCallable`, `CompletionProvider`, `CompletionRegistry`, `invoke_provider`, `normalize_candidate` |

Generic lifecycle, metadata, state, context, logging, dependency, and elevation
contracts remain owned by `engulf-api` and are imported from `engulf_api`.
