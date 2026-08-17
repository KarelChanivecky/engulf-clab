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

Import public contracts from `engulf_api`, not from its implementation modules.
`PLUGIN_API_MAJOR` is `1` and `PLUGIN_API_VERSION` is `"1.0.0"`. The major is part
of normal-plugin entry-point groups; a goal's independently versioned compatibility
boundary is its `GoalRequirement`.

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

`Goal.setup(api)` is an optional one-time operation performed after selected plugins
have been discovered, validated, ordered, and checked for elevation. `Goal.achieve()`
runs once per non-diagnostic invocation. A goal instance belongs to one application,
so reusable application definitions must construct a fresh goal each time.

`GoalRequirement` is the technical compatibility boundary:

- `goal_id` is a lowercase, globally qualified identifier.
- `api_major` changes when that goal's plugin contract becomes incompatible.
- `GoalContract.plugin_type` is checked at runtime after an activated plugin is
  imported.

Application policy can activate a plugin that did not name that application, but
it cannot bypass these checks.

## Results And Invocation

`Invocation` contains immutable `arguments`, canonical absolute `cwd`, and an
immutable snapshot of the string `environment` mapping. Arguments cannot contain
NUL characters. `GoalResult[T]` carries `status`, `exit_code`, typed `value`,
optional `error`, optional `rejected_by`, and `diagnostic_ids`:

- `COMPLETED`: the goal ran to its defined completion, even if its domain exit code
  is nonzero.
- `REJECTED`: a plugin or goal vetoed the operation before its normal work.
- `FAILED`: goal work started or was attempted but did not succeed.
- `FRAMEWORK_FAILED`: lifecycle, callback, contract, or cleanup infrastructure
  failed. Engulf uses exit code 70 by default.
- `DIAGNOSTIC`: one or more isolated diagnostics handled the invocation; the result
  records their stable IDs.

Use the factory matching the framework disposition:

| Factory | Important fields |
| --- | --- |
| `GoalResult.completed(value=None, *, exit_code=0)` | Domain work completed; a nonzero domain exit is allowed. |
| `GoalResult.rejected(exit_code, value=None, *, rejected_by=None, error=None)` | Work was vetoed or preempted. The runtime attributes an unattributed outer-hook rejection to that plugin. |
| `GoalResult.failed(exit_code, value=None, *, error=None)` | Domain work was attempted and failed. |
| `GoalResult.framework_failed(*, exit_code=70, error=None)` | Framework, callback, validation, or cleanup failure. |
| `GoalResult.diagnostic(ids, *, exit_code=0, error=None)` | A nonempty, unique tuple of diagnostic IDs handled the call. |

`contributing_diagnostic_ids` is an alias for `diagnostic_ids` for callers that want
to emphasize attribution.

Goal-specific API packages that define process outcomes should reuse
`validate_exit_code()` for exact integer exit codes from 0 through 255. Booleans are
rejected even though Python treats them as integers.

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

The default dependency is middleware-shaped: the dependency is `BEFORE` its
dependent in preprocessing and `AFTER` it in postprocessing. Either position may be
`None` to omit that phase's ordering edge while retaining the hard presence
requirement. Dependency metadata is separate from wheel installation dependencies
and from context access declarations.

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

The abstract API types make the lifecycle surface explicit:

| API | Capabilities |
| --- | --- |
| `DiagnosticsAPI` | Immutable `application` metadata and `logger`. |
| `RegistrationAPI` | Diagnostics plus the process `elevated` snapshot. |
| `GoalSetupAPI` | Registration facilities, `application_id`, `display_name`, preprocessing-ordered `plugin_ids`, and setup-phase `dispatch()`. |
| `InvocationAPI` | Diagnostics, elevation, context, state, known workspaces, and leases. |
| `BeforeGoalAPI` / `AfterGoalAPI` | Lifecycle-specific names for the same invocation capabilities. |
| `GoalAPI` | Goal-owned invocation capabilities plus invocation-phase `dispatch()`. |

`PluginLogger` supports the standard `debug`, `info`, `warning`, `error`,
`exception`, `critical`, `log`, `isEnabledFor`, and `name` surface. It intentionally
does not expose handler or level mutation.

## Invocation Context

Context is an in-memory object table created for one `Application.invoke()` and
shared by the goal and every entered plugin callback in that invocation. It is not
persistent state and is reset before the next invocation.

Plugins must declare every globally qualified identifier they may access in
`context_reads` and `context_writes`. Undeclared access raises `ContextAccessError`;
metadata does not create ordering edges, so declare a `PluginDependency` when a
reader must run after a writer. The goal API may coordinate all goal-owned context
identifiers without adding plugin metadata.

- `get_context(id, default=None)` returns the default when no value exists. A miss
  does not count as a successful read.
- `require_context(id)` returns the value or raises `MissingContextError`.
- `set_context(id, value)` creates or replaces any earlier value; values are
  arbitrary in-process Python objects.
- At invocation cleanup, Engulf emits one `UnusedContextWarning` listing sorted IDs
  that were written but never successfully read.

Context declarations describe access only. They do not imply transportability,
trust, data ownership, or plugin dependency order.

## State Store Operations

`api.state(StateScope.USER)` returns participant state shared across invocations and
workspaces. `api.state(StateScope.WORKSPACE)` returns a `WorkspaceState` for the
canonical current workspace. The goal receives the same contracts under a reserved
goal namespace. Repeated requests for the same scope in one invocation return the
same handle.

| `StateStore` member | Behavior |
| --- | --- |
| `directory` | Create and return the namespaced directory for caller-managed trees. |
| `path(filename)` | Validate one path component, create the store, and return its child path. |
| `exists(filename)` | Test a child without creating the store. |
| `read_bytes()` / `read_text()` | Read a protected child; text defaults to UTF-8 with strict errors. |
| `write_bytes()` / `write_text()` | Atomically replace one child with private ownership and permissions. |
| `delete(filename, missing_ok=False)` | Unlink one named child file. It is not a recursive tree-removal API. |
| `transaction(timeout=None)` | Hold the exclusive store lock and return the same store for a serialized operation sequence. |

Every filename API accepts exactly one nonempty path component, never `.` or `..`,
an absolute path, a separator, or NUL. `directory` and `path()` deliberately expose
a filesystem view for structures such as cloned repositories; operations inside
such caller-managed trees are the plugin's responsibility.

`WorkspaceState.root` is the canonical workspace represented by the handle.
`destroy()` idempotently queues removal of that participant's entire workspace
namespace after postprocessing. `known_workspaces()` returns only workspace records
in which that participant has state and supports global cleanup operations such as
destroy-all.

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

## Isolated Diagnostic Contract

`DiagnosticPlugin` is a separate contract for import-free, sandboxed diagnostics.
It is not a subclass of `Plugin`, has no normal lifecycle hooks, and is not selected
by application `PluginPolicy`. Implement one read-only operation:

```python
from engulf_api import (
    DiagnosticAPI,
    DiagnosticContribution,
    DiagnosticPlugin,
    DiagnosticRequest,
)


class InventoryDiagnostic(DiagnosticPlugin):
    def diagnose(
        self,
        request: DiagnosticRequest,
        api: DiagnosticAPI,
    ) -> DiagnosticContribution:
        lines = [
            f"{record.preprocess_position}: {record.plugin_id}"
            for record in api.plugin_executions
        ]
        api.logger.debug("reporting %d normal plugins", len(lines))
        return DiagnosticContribution(stdout="\n".join(lines) + "\n")


diagnostic = InventoryDiagnostic()
```

`DiagnosticRequest` provides the original immutable argument tuple, immutable
`ApplicationMetadata`, and `GoalRequirement`, with convenience properties for the
same values as `application_id`, `goal_id`, and `goal_api_major`. It deliberately
contains no current directory, environment, home, workspace, state, context, or
lease handles.

`DiagnosticAPI` exposes only immutable inspection data:

- `active_plugins` (also available as `plugins`) contains `ActivePlugin` records in
  preprocessing order;
- `plugin_executions` (also `normal_plugins` or `plugin_records`) adds one-based
  preprocessing and postprocessing positions through `PluginExecutionRecord`;
- `diagnostic_extensions` contains every import-free `DiagnosticExtension` record,
  including `diagnostic_id`, `triggers`, `distribution`, `version`, `target`,
  `available`, and `unavailable_reason`;
- `elevated` is the host application's elevation snapshot;
- `logger` buffers standard logging methods for the diagnostic response.

Each `PluginExecutionRecord` contains the underlying `plugin` descriptor plus
one-based `preprocess_position` and `postprocess_position`, with convenience
`plugin_id`, `metadata`, and `source` properties.

Return `DiagnosticContribution(stdout=..., stderr=..., exit_code=...)`. Output is
text and the exit code is an exact value from 0 through 255. The runtime owns
packaging, trigger matching, output limits, aggregation, and isolation; see
[`engulf` diagnostic authoring](engulf-runtime.md#authoring-a-diagnostic-extension).

## Provenance And Inspection Records

`PluginMetadata` is what an adapter declares. `PluginSource` is what the runtime
observed about how it obtained that adapter. `ActivePlugin` combines the two without
retaining a live implementation.

`ActivePlugin` exposes its `metadata` and `source` directly and delegates
`plugin_id`, `goal_requirement`, `priority`, `elevation_requirement`,
`plugin_dependencies` (also `dependencies`), `context_reads`, and `context_writes`
for convenient inspection.

`PluginSourceKind` has `INSTALLED`, `DIRECTORY`, and `DIRECT`. Installed records may
include `distribution_name`, `distribution_version`, exact `entry_point_group`, and
`entry_point_value`; every record has a diagnostic `target`. Directory records
include a canonical absolute `directory`. `normalized_distribution_name` provides
PEP-style `-`, `_`, and `.` normalization for comparison. None of these records
prove integrity, publisher identity, authorization, or trust.

`plugin_name(plugin)` returns the Python module and qualified class name for
diagnostics. It is not a stable plugin identity; use `plugin_id` for compatibility,
ordering, attribution, state, and policy.

## Contract Errors And Validation

| Public type or helper | Meaning |
| --- | --- |
| `ContextAccessError` | A plugin attempted an undeclared context read or write. |
| `MissingContextError` | `require_context()` found no value. |
| `PluginPhaseError` | A callback-bound API, logger, state handle, or lock context was used outside its valid callback. |
| `LockTimeoutError` | A state transaction or resource lease missed its one deadline. |
| `StateCatalogError` | Centrally managed workspace metadata or protected state layout was invalid. |
| `UnusedContextWarning` | One or more written context IDs were never read. |
| `validate_global_identifier(value, label=...)` | Require a lowercase, dot-qualified identifier with at least two segments; each begins and ends with a letter or digit and may contain internal `_` or `-`. |
| `validate_exit_code(value, label="exit_code")` | Require an exact `int` from 0 through 255; `bool` is rejected. |

Construction-time validation errors normally use `TypeError` for the wrong value
kind and `ValueError` for an invalid value. Callback failures are converted by the
runtime to attributed framework failures; goal setup failures instead abort
application construction.

## Public Import Surface

The top-level package exports these supported names, grouped by responsibility:

| Area | Names |
| --- | --- |
| Version | `PLUGIN_API_MAJOR`, `PLUGIN_API_VERSION` |
| Application | `ApplicationMetadata` |
| Goal and invocation | `Goal`, `GoalContract`, `GoalRequirement`, `GoalResult`, `GoalResultStatus`, `Invocation`, `GoalPhase`, `PluginOrder`, `AttributedContribution` |
| Normal plugins | `Plugin`, `PluginMetadata`, `PluginDependency`, `DependencyPosition`, `ElevationRequirement`, `ActivePlugin`, `PluginSource`, `PluginSourceKind`, `plugin_name` |
| Managed callback APIs | `DiagnosticsAPI`, `RegistrationAPI`, `GoalSetupAPI`, `InvocationAPI`, `BeforeGoalAPI`, `AfterGoalAPI`, `GoalAPI`, `PluginLogger` |
| State | `StateScope`, `StateStore`, `WorkspaceState` |
| Diagnostics | `DiagnosticPlugin`, `DiagnosticRequest`, `DiagnosticAPI`, `DiagnosticContribution`, `DiagnosticExtension`, `PluginExecutionRecord` |
| Errors and validation | `ContextAccessError`, `MissingContextError`, `PluginPhaseError`, `LockTimeoutError`, `StateCatalogError`, `UnusedContextWarning`, `validate_global_identifier`, `validate_exit_code` |

## Packaging A Goal API

A reusable goal with third-party plugins should publish its compatibility contract
separately from both its application and goal runtime. The goal API wheel owns the
`GoalRequirement`, plugin adapter base, frozen events/contributions, phase adapters,
and any local-only registration protocols. It depends on `engulf-api`, remains
side-effect free and OS-independent where possible, ships `py.typed`, and defines no
console script or plugin entry point itself.

```toml
[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"

[project]
name = "example-report-api"
version = "1.0.0"
requires-python = ">=3.14"
dependencies = ["engulf-api>=1.0,<2"]

[tool.hatch.build.targets.wheel]
packages = ["src/example_report_api"]
```

The application/goal runtime may depend on `engulf` and this API wheel. A plugin
wheel depends on `engulf-api` and this goal API wheel—not on the application or
runtime implementation—and publishes its adapter under the exact goal catalog. For
goal `com.example.report` major 1, that group is:

```text
engulf.plugins.v1.goal.v1.com_example_report
```

Change the goal API major only for incompatible plugin-contract changes. Package
versions and the framework's `PLUGIN_API_MAJOR` remain separate axes.

## Versioning

`PLUGIN_API_MAJOR` remains `1`. Entry-point groups encode this major. Goal APIs have
their own major in `GoalRequirement`, so one goal contract can evolve independently
of another. This repository is still developing its first release; existing package
versions are not bumped for these changes.
