# engulf-api

`engulf-api` is the dependency-free public contract shared by Engulf goals and
plugins. It intentionally contains no plugin discovery, process runner, completion
engine, or filesystem implementation.

It also defines `DiagnosticPlugin`, `DiagnosticRequest`, `DiagnosticAPI`, and
`DiagnosticContribution` for isolated diagnostic extensions. A diagnostic request
contains sanitized arguments and application/goal identity only. It deliberately
has no current directory, workspace, home, or environment. Diagnostic extensions
are not normal goal plugins and do not receive lifecycle or goal-phase APIs.

The package is typed, OS-independent, and requires Python 3.14 or newer.

## Goal Contract

Every application selects exactly one `Goal`. The goal describes both the outcome
of an invocation and the process used to reach it.

```python
from engulf_api import (
    Goal,
    GoalAPI,
    GoalContract,
    GoalRequirement,
    GoalResult,
    Invocation,
    Plugin,
)

REQUIREMENT = GoalRequirement("com.example.report", 1)


class ReportPlugin(Plugin):
    goal_requirement = REQUIREMENT


class ReportGoal(Goal[str]):
    contract = GoalContract(REQUIREMENT, ReportPlugin)

    def achieve(self, invocation: Invocation, api: GoalAPI) -> GoalResult[str]:
        report = build_report(invocation.arguments)
        return GoalResult.completed(report)
```

`GoalRequirement` is the technical compatibility boundary:

- `goal_id` is a lowercase, globally qualified identifier.
- `api_major` changes when that goal's plugin contract becomes incompatible.
- `GoalContract.plugin_type` is checked at runtime after an activated plugin is
  imported.

Application policy can activate a plugin that did not name that application, but
it cannot bypass these checks.

## Results And Invocation

`Invocation` contains immutable arguments, canonical current directory, and an
immutable environment mapping. `GoalResult[T]` carries a typed value, exit code,
optional error, and one of these statuses:

Goal-specific API packages that define process outcomes should reuse
`validate_exit_code()` for exact integer exit codes from 0 through 255. Booleans are
rejected even though Python treats them as integers.

- `COMPLETED`: the goal ran to its defined completion, even if its domain exit code
  is nonzero.
- `REJECTED`: a plugin or goal vetoed the operation before its normal work.
- `FAILED`: goal work started or was attempted but did not succeed.
- `FRAMEWORK_FAILED`: lifecycle, callback, contract, or cleanup infrastructure
  failed. Engulf uses exit code 70 by default.
- `DIAGNOSTIC`: one or more isolated diagnostics handled the invocation; the result
  records their stable IDs.

`Application.invoke()` returns the complete result. `Application.run()` returns only
its exit code.

## Application Metadata

Every registration, lifecycle, goal, and goal-specific phase API exposes the same
immutable `api.application` value:

```python
metadata = api.application
api.logger.info(
    "%s %s %s",
    metadata.vendor,
    metadata.product,
    metadata.version,
)
```

`ApplicationMetadata` contains `application_id`, `display_name`, `vendor`, `product`,
`short_product_name`, and `version`. `product` is the full presentation name, while
`short_product_name` is its concise presentation counterpart. Plugins may use the
descriptive fields to derive presentation, environment-variable prefixes, and other
application-facing conventions. Values are nonempty strings without surrounding
whitespace or control characters; plugins remain responsible for any stricter
normalization required by an external format.

Only `application_id` is technical identity. Vendor, product, short product name,
version, and display name do not affect goal compatibility, state paths, lease
identity, elevation, activation, or trust. The API property is callback-bound,
although the returned frozen metadata value may be retained.
`GoalSetupAPI.application_id` and `display_name` remain convenience aliases for the
corresponding metadata fields.

## Plugin Lifecycle

All goal-specific plugin classes derive from `Plugin` and declare:

```python
from engulf_api import ElevationRequirement


class ExamplePlugin(Plugin):
    plugin_id = "com.example.report.audit"
    goal_requirement = REQUIREMENT
    priority = 50
    elevation_requirement = ElevationRequirement.NONE
    plugin_dependencies = ()
    context_reads = frozenset()
    context_writes = frozenset()
```

The inherited `metadata` property returns these declarations as one immutable,
keyword-only `PluginMetadata` value. Engulf snapshots it during discovery. Declare
metadata without import-time probes or side effects, and do not mutate it after
application construction. Runtime implementations may obtain equivalent metadata
without retaining a live plugin object in the application process.

`elevation_requirement` has three exact values:

- `NONE` (the default): the plugin does not claim elevated behavior.
- `OPTIONAL`: the plugin activates in either mode and branches on `api.elevated`.
- `REQUIRED`: application construction raises `PluginElevationError` when the
  process is not elevated, before goal setup or plugin registration callbacks run.

Engulf detects root effective UID on POSIX and token elevation on Windows. It does
not invoke `sudo`, display a UAC prompt, or restart the process. Elevation is plugin
runtime metadata, so a selected installed plugin is imported before the declaration
can be validated; plugin modules must remain free of import-time side effects.
`ElevationRequirement` does not authorize code or isolate it. In the current
runtime, every selected plugin executes in the application process with the same
authority as the application.

The optional universal outer hooks are:

```python
def before_goal(self, invocation, api):
    # Return None to continue or GoalResult to short-circuit.
    return None


def after_goal(self, invocation, result, api):
    # Return the unchanged or transformed result.
    return result
```

Before hooks use preprocessing order. The first non-`None` result stops later before
hooks and skips the goal. After hooks run in postprocessing order only for plugins
whose before hook completed, including the plugin that short-circuited. Their result
transformations compose as middleware.

## Goal Phases

A goal invokes goal-specific plugin methods through typed `GoalPhase` declarations:

```python
from dataclasses import dataclass
from engulf_api import GoalPhase, InvocationAPI, PluginOrder


@dataclass(frozen=True)
class Finding:
    message: str


def inspect(plugin, event, api: InvocationAPI) -> Finding | None:
    return plugin.inspect(event, api)


INSPECT = GoalPhase(
    phase_id="com.example.report.inspect",
    order=PluginOrder.PREPROCESS,
    local_callback=inspect,
    contribution_type=Finding,
)

findings = api.dispatch(INSPECT, event)
```

Dispatch returns `AttributedContribution[Finding]` values after every callback has
run. Each value carries the stable `plugin_id`. A plugin cannot see another plugin's
contribution while its own callback is running. Contribution objects should be
immutable; the runtime validates the declared contribution type.

Only two dependency orders exist: `PREPROCESS` and `POSTPROCESS`. Each goal phase
selects one. Setup phases normally use preprocessing order.

`phase_id` is the stable routing identity and must remain unique within the goal
contract. `local_callback` is the in-process adapter for that phase, not its
identity. Keep the adapter module-level, deterministic, and limited to forwarding to
the goal-specific plugin method; do not capture invocation state in a closure.

Phase events and contributions should be immutable, explicitly typed values rather
than open object graphs, mutable registries, or application implementation objects.
That discipline permits a future execution backend to add goal-owned transport
codecs without replacing `GoalPhase`. It does not mean current values are serialized
or that arbitrary existing phases can automatically run out of process.

## Dependencies And Priority

`PluginDependency` is a hard active-plugin dependency with independent ordering:

```python
from engulf_api import DependencyPosition, PluginDependency

plugin_dependencies = (
    PluginDependency(
        "com.example.report.source",
        preprocess=DependencyPosition.BEFORE,
        postprocess=DependencyPosition.AFTER,
    ),
)
```

Dependencies do not activate packages. If policy leaves a required plugin inactive,
application construction fails. Priority defaults to 50 and only breaks ties among
plugins currently ready in the dependency graph; higher values run first.

## Managed Invocation API

`InvocationAPI` provides:

- an initialized, lifecycle-bound `PluginLogger`;
- the process elevation snapshot through `api.elevated`;
- declared context reads and writes;
- user and workspace state stores;
- known workspace enumeration and deferred destruction;
- process-safe state transactions;
- application/user-scoped named resource leases.

The goal receives the same facilities through `GoalAPI`, using a reserved goal-owned
state namespace. Registration callbacks receive initialized logging and the same
read-only elevation snapshot through `RegistrationAPI`.

All capabilities are callback-bound. Retained loggers, stores, transactions, leases,
and APIs fail after the callback ends. Hook cleanup forcibly releases leaked locks.

## State Transactions

Individual writes are atomic, but atomic writes do not make a read-modify-write
sequence atomic. Use a transaction:

```python
import json
from engulf_api import StateScope

state = api.state(StateScope.USER)
with state.transaction(timeout=10) as locked:
    records = json.loads(locked.read_text("records.json"))
    records[key] = value
    locked.write_text("records.json", json.dumps(records))
```

Transactions serialize cooperating state access; they do not roll back. Writes made
before an exception remain committed. Nested or overlapping transactions through one
API are rejected.

## Resource Leases

Leases coordinate long-running external work between cooperating Engulf processes
that share a resolved state location and application ID:

```python
with api.leases(
    (
        f"docker-image:{image}",
        f"vrnetlab-builder:{builder.resolve()}",
    )
):
    build_or_inspect_external_resources()

    with state.transaction() as locked:
        # Re-read, merge, and atomically save fingerprint state.
        ...
```

Acquire all external-resource leases first, then use short state transactions. Lease
names are exact and case-sensitive. Multi-lease acquisition validates, deduplicates,
sorts, applies one deadline, and releases in reverse order.

Leases do not establish ownership against unrelated tools or different users.
External resources still require ownership markers and recovery journals.

## Versioning

`PLUGIN_API_MAJOR` remains `1`. Entry-point groups encode this major. Goal APIs have
their own major in `GoalRequirement`, so one goal contract can evolve independently
of another. This repository is still developing its first release; existing package
versions are not bumped for these changes.
