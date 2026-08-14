# engulf

`engulf` is the managed runtime for goal-oriented, plugin-based CLI applications.
It depends on `engulf-api` and implements application lifecycle, installed-plugin
discovery, dependency ordering, diagnostics, persistent state, transactions,
resource leases, and workspace cleanup.

The runtime supports POSIX and Windows. Goals and plugins may impose narrower
platform requirements, but discovery, lifecycle, diagnostics, context, and managed
state do not require the executable-wrapper runtime.

It does not contain executable-wrapper events, argument edits, process execution,
help aggregation, or shell completion. Those live in the executable-wrapper goal
packages.

## Constructing An Application

```python
from engulf import ApplicationDefinition, PluginPolicy
from my_report_goal import ReportGoal

REPORT_APPLICATION = ApplicationDefinition(
    application_id="com.example.report-cli",
    display_name="report-cli",
    goal_factory=ReportGoal,
    vendor="Example Corp",
    product="Report CLI",
    short_product_name="Report",
    version="1.4.0",
    plugin_policy=PluginPolicy.declared(
        include={"com.example.shared.audit"},
    ),
)


def main() -> int:
    with REPORT_APPLICATION.create() as application:
        return application.run()
```

`ApplicationDefinition` is immutable and side-effect free. Importing it does not
instantiate the goal, discover plugins, or run setup. Every `create()` call invokes
`goal_factory` and returns a fresh managed `Application`. Applications that do not
need reuse may still construct `Application` directly as the lower-level API.

`application_id` is normalized to lowercase distribution form. Keep it stable: it
participates in plugin discovery, state paths, and named lease identity.

Each created `Goal` instance belongs to one application. `Goal.setup()` runs once
after plugin discovery. Every `invoke()` creates a fresh `Invocation`, context
table, state manager, diagnostics session, and lifecycle capability set.

`Application.close()` is idempotent and releases plugin execution endpoints.
`invoke()` and `run()` reject use after close. Long-lived applications may invoke
repeatedly and close during shutdown, but overlapping invocations on one application
are rejected because goal and plugin endpoints are application-owned. Closing during
an active invocation is also rejected. Scoped applications can use a context manager:

```python
with REPORT_APPLICATION.create() as application:
    result = application.invoke(arguments)
```

### Editions And Forks

An edition is another launcher for the same logical application. It changes the
command-facing name and adds optional or required plugins while preserving the base
application ID:

```python
from report_app_core import REPORT_APPLICATION

VENDOR_REPORT = REPORT_APPLICATION.edition(
    display_name="vendor-report",
    vendor="Vendor Corp",
    product="Vendor Report",
    short_product_name="VReport",
    version="1.4.0-vendor.2",
    include_plugins={"com.vendor.optional-export"},
    require_plugins={"com.vendor.policy"},
)
```

The edition shares the base application's plugin declaration group, user and
workspace state, named lease namespace, and any future application-scoped policy.
Both launchers must therefore remain behaviorally and state-schema compatible.
Goals supporting editions must derive command-facing names from
`GoalSetupAPI.display_name` instead of hard-coding the official executable name.
Every callback receives the edition's immutable metadata through `api.application`,
so plugins can adapt labels and environment-variable conventions without knowing the
launcher at build time. Omitted edition metadata fields inherit from the base.

A fork reuses the goal factory and defaults under an independent identity:

```python
INDEPENDENT_REPORT = REPORT_APPLICATION.fork(
    application_id="com.vendor.report",
    display_name="vendor-report",
    vendor="Vendor Corp",
    product="Vendor Report",
    short_product_name="VReport",
    version="2.0.0",
    inherit_declarations=True,
)
```

Fork state and leases are isolated. `inherit_declarations=True` explicitly adds the
base and ancestor application groups to declared-mode discovery; it does not share
state or grant trust. Without that flag, only the fork's own application group is
read. Allowlist and blocklist policies continue to ignore application declarations.

For packaging, put the goal and definition in a script-free core wheel. The
official and vendor launcher wheels depend on that core and define their own console
scripts. This avoids installing the official command as a side effect of installing
the vendor edition. A vendor-only plugin should publish its goal-catalog entry but
not declare the shared application ID; the vendor definition includes it explicitly,
so the official launcher does not activate it merely because it is installed.

`PluginPolicy.including()` expands a policy without changing its mode. It unions IDs
into declared and allowlist policies and removes IDs from blocklist exclusions.
Blocklist exclusions are therefore defaults an edition may override, not a security
denylist.

Vendor, product, short product name, version, and display name are descriptive
metadata. They never replace `application_id` in discovery, state, lease,
compatibility, elevation, or trust decisions. Applications expose the same value as
`application_metadata` and convenience `vendor`, `product`, `short_product_name`,
and `version` properties.

`application.active_plugins` and its `application.plugins` alias return immutable
`ActivePlugin` descriptors, never live implementation objects. Each descriptor
contains plugin-declared `PluginMetadata` and runtime-captured `PluginSource` data.
Installed sources retain distribution name/version and exact entry-point group and
target when available; directory sources retain their canonical directory. This
separation lets later execution policies inspect provenance without changing goal
or plugin metadata. A source record does not attest package integrity, publisher
identity, secure installation, or trust.

## Execution And Trust

The current endpoint implementation is in-process. Every selected plugin module,
factory, setup callback, lifecycle hook, and goal phase executes with the
application's operating-system authority. Activation policy is not trust policy,
`ElevationRequirement` is not authorization, and plugin state namespaces do not
prevent same-user filesystem access outside the API.

Do not install or activate untrusted plugins in an elevated application. The Python
environment, application package, and application-owned plugin directory must not be
writable by a less-privileged user. Strong privilege separation should keep the
general Python application unprivileged and expose narrowly validated privileged
operations through a separate broker.

Dispatch already goes through an internal execution endpoint and uses stable goal
phase IDs. This is a migration seam, not a sandbox: no remote endpoint, trust grant,
or privilege-dropping worker is currently implemented.

Any future execution policy remains separate from `PluginPolicy`. Existing phases
without a goal-defined transport form remain explicitly local-only; they are not
silently serialized. A hardened application may later reject such plugins, while
legacy applications can retain in-process behavior. Plugins may declare execution
compatibility in a future contract, but only the application can authorize an
execution mode.

### Isolated Diagnostic Extensions

Diagnostics use import-free goal catalogs under
`engulf.diagnostics.v1.goal.v<major>.<goal-id>` and a matching
`.triggers.before_separator` group. The catalog name is the stable diagnostic ID;
trigger names are exact reserved `--options`. Both declarations must have identical
distribution, version, and target provenance. Diagnostics activate independently of
`PluginPolicy` and run in deterministic distribution/ID order.

Unlike normal plugins, a diagnostic target is imported only after a Linux
Bubblewrap worker has isolated user, process, IPC, network, UTS, and cgroup
namespaces, removed capabilities, applied resource limits, and installed a seccomp
filter. Communication is bounded JSON, never pickle. A matching diagnostic
invocation suppresses every invocation-time normal hook, goal phase, goal action,
and wrapped executable. Goal setup still runs once during application construction.

If Bubblewrap or required kernel isolation is unavailable, diagnostic targets stay
unimported. Engulf emits one construction warning, continues ordinary invocations,
and returns framework exit 70 for a declared diagnostic trigger rather than passing
it through to the goal. Kernel vulnerabilities and side channels are outside this
boundary; normal plugins remain fully trusted in-process code.

## Invocation Lifecycle

One invocation follows this order:

1. Validate arguments and resolve per-invocation logging controls.
2. Create immutable invocation, context, state, and diagnostics facilities.
3. Run universal `before_goal` hooks in preprocessing order.
4. Stop at the first returned `GoalResult`, or call `Goal.achieve()`.
5. Let the goal dispatch any typed inner phases it defines.
6. Run `after_goal` middleware in postprocessing order for entered plugins.
7. Release capabilities, finalize requested workspace destruction, and report unused
   context writes.

Callback exceptions become `FRAMEWORK_FAILED` results with exit code 70. Goal phase
exceptions identify the stable `plugin_id`, not a Python class name.

Use `application.invoke(args)` when the typed `GoalResult` matters. Use
`application.run(args)` for a console entry point.

## Installed Plugin Catalogs

Installed discovery reads entry-point identity and distribution metadata before
importing plugin modules. Plugin-declared ordering, context, dependency, and
elevation metadata is snapshotted as `PluginMetadata` after import. A plugin package
can publish two kinds of declaration.

### Goal Catalog

Every installed plugin adapter must be registered in its exact goal catalog:

```text
engulf.plugins.v<PLUGIN_API_MAJOR>.goal.v<GOAL_API_MAJOR>.<normalized_goal_id>
```

For goal `org.engulf.executable-wrapper` API major 1, the group is:

```text
engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper
```

The entry-point name must be the exact stable `plugin_id`:

```toml
[project.entry-points."engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper"]
"com.example.audit" = "example_audit:plugin"
```

The group selects goal ID and major before import. After import, Engulf also checks
the plugin's `GoalRequirement`, required runtime plugin type, and exported
`plugin_id`.

### Plugin-Side Application Declaration

A plugin opts into one application by repeating the same ID and target in the
application group:

```toml
[project.entry-points."engulf.plugins.v1.application.com_example_cli"]
"com.example.audit" = "example_audit:plugin"
```

To support multiple applications, add one application-group entry for each. The
goal-catalog implementation remains single and reusable. An application declaration
must come from the same distribution, version, and import target as the matching
goal-catalog entry.

Use the exported helpers to compute exact groups:

```python
from engulf import (
    application_plugin_entry_point_group,
    goal_plugin_entry_point_group,
)

print(application_plugin_entry_point_group("com.example.cli"))
print(goal_plugin_entry_point_group("org.engulf.executable-wrapper", 1))
```

## Application-Side Activation Policies

Technical goal compatibility is always mandatory. Within that compatible catalog,
the application selects one policy:

```python
# Either the plugin names this app or the app includes the ID.
PluginPolicy.declared(include={"com.example.audit"})

# Ignore plugin-side app declarations; activate only these named IDs.
PluginPolicy.allow_only({"com.example.audit"})

# Also activate their transitive PluginDependency targets.
PluginPolicy.allow_only(
    {"com.example.audit"},
    include_dependencies=True,
)

# Activate every goal-compatible installed plugin except these IDs.
PluginPolicy.allow_all_except({"com.example.unsafe"})
```

Explicit IDs are optional: an ID absent from the current goal catalog is skipped and
listed by `application.missing_policy_ids`. This supports optional installations.
`ApplicationDefinition.required_plugin_ids`, `edition(require_plugins=...)`, and
`Application(required_plugin_ids=...)` select IDs and make their absence a
construction-time `PluginRequirementError` before goal setup. Required plugin wheels
should also be ordinary package dependencies so installation and activation agree.

By default, every dependency of an allowlisted plugin must also be explicitly
allowlisted. Set `include_dependencies=True` to activate reachable
`PluginDependency` targets recursively from the same goal catalog or plugin
directory. Dependencies that are unavailable still fail application construction.
Implicit dependencies do not need plugin-side application declarations because the
application's allowlist selected them, but exact goal ID, goal API major, and runtime
plugin type checks still apply.
The option is valid only for `allow_only()`; declared and blocklist policies already
define their complete candidate sets.

An application exposes `plugin_declaration_application_ids` and
`application_plugin_entry_point_groups` for declaration-lineage introspection. The
current application ID is always first; inherited IDs are normalized and
deduplicated. Every declaration must still match the same goal-catalog distribution,
version, and target.

Catalog IDs are validated and deduplicated before any selected target is imported.
An unselected goal-catalog entry is not imported. Blocklist mode deliberately
selects and imports every compatible catalog entry not blocked.

## Local Plugin Directory

`plugin_dir` supports application-owned development plugins. Every immediate,
non-private `*.py` file must export `plugin` as an instance or zero-argument factory.
Private helper modules remain importable. Files load in lexical order.

Supplying a directory is itself an application-side declaration, so declared mode
activates all technically compatible directory plugins. Allowlist and blocklist
filter directory plugins by their exported IDs after import. Directory code cannot
be filtered before import because it has no installed metadata catalog.

## Dependencies And Ordering

Engulf resolves two deterministic topological orders:

- preprocessing for outer before hooks and goal phases that choose `PREPROCESS`;
- postprocessing for outer after hooks and goal phases that choose `POSTPROCESS`.

`PluginDependency` expresses presence and independent edges for both orders.
Priority defaults to 50 and breaks ties only among currently ready nodes. Higher
priority runs first. Duplicate IDs, missing dependencies, self-dependencies, repeated
dependency declarations, and cycles are startup errors.

Package dependencies in a plugin wheel make another wheel available; they do not
activate its plugin entry point. Both adapters must still be selected by application
policy, either explicitly or through `allow_only(..., include_dependencies=True)`.
Implicit activation follows Engulf `PluginDependency` metadata, not Python package
dependency metadata.

## Elevation

Plugins declare one `ElevationRequirement`: `NONE`, `OPTIONAL`, or `REQUIRED`.
Required elevation is validated after discovery and ordering but before goal setup
or any plugin registration callback. A selected required plugin in an unprivileged
process raises `PluginElevationError`; Engulf does not elevate or restart itself.

Optional plugins remain active without elevation and can degrade deliberately:

```python
from engulf_api import ElevationRequirement


class NetworkPlugin(MyGoalPlugin):
    elevation_requirement = ElevationRequirement.OPTIONAL

    def before_goal(self, invocation, api):
        if api.elevated:
            configure_system_networking()
```

`api.elevated` is available during registration and invocation callbacks and is
callback-bound like the other capabilities. `Application.elevated` exposes the same
process snapshot to application code. On POSIX elevation means effective UID zero;
on Windows it means an elevated process token.

This is observation only. Required elevation rejects an incompatible launch, but it
does not prove that a plugin is trusted or limit other plugins. When the application
is elevated, all selected plugins are elevated too.

## Logging

Each registration and invocation callback receives `api.logger`, already configured
for that plugin. The logger intentionally omits handler and level mutation methods.
It is valid only during the active callback.

```python
def before_goal(self, invocation, api):
    api.logger.debug("checking %d arguments", len(invocation.arguments))
```

Applications configure defaults with `LoggingConfig` and can override levels per
invocation with `LogLevelOverrides`. Every application reserves:

```text
--<display-name>-log-level LEVEL
--<display-name>-plugin-log-level PLUGIN_ID=LEVEL
```

Controls before `--` are removed from the goal's arguments. Controls after `--` are
left untouched. Registration logging uses the initialized setup diagnostics session;
catalog candidates that are never activated are never imported and therefore cannot
log.

## State And Workspaces

Plugins and the goal receive API-namespaced user and workspace stores:

```python
from engulf_api import StateScope

user = api.state(StateScope.USER)
workspace = api.state(StateScope.WORKSPACE)
user.write_text("settings.json", data)
workspace.write_bytes("artifact", payload)
```

One filename is one path component. Reads reject symbolic links and Windows reparse
points. Writes are atomic, private, and owner-aware. Calling `directory` or `path()`
exposes the namespaced directory so plugins can clone repositories or manage
directory trees inside their own namespace. `delete()` removes a named file or tree.
`WorkspaceState.destroy()` queues namespace destruction after postprocessing; an
empty workspace record is pruned.

On POSIX, the default state home follows `XDG_STATE_HOME` or `~/.local/state`. Under
a valid sudo invocation, state uses the invoking non-root user's home and ownership.
On Windows, it uses `%LOCALAPPDATA%\Engulf\State`, the process-token user SID,
protected owner/SYSTEM/Administrators DACLs, and non-inheritable `LockFileEx`
handles. POSIX uses private modes, ownership, no-follow opens, and `flock`.

`StateHomeResolver` and `WorkspaceRootResolver` are application policy and receive
stable context records. `StateHomeContext` exposes `application_id`, a
platform-qualified `owner_id`, `owner_home`, and whether the process is elevated;
it does not expose platform-specific UID/GID or sudo fields.

## Transactions And Leases

Atomic file replacement does not serialize read-modify-write sequences:

```python
with user.transaction(timeout=5) as locked:
    value = int(locked.read_text("counter"))
    locked.write_text("counter", str(value + 1))
```

Transactions serialize; they do not roll back. Ordinary reads take shared store
locks, writes take exclusive locks, and workspace destruction waits for the affected
store lock.

Named leases coordinate external resources across cooperating Engulf processes that
share state owner/home and application ID:

```python
with api.leases((f"docker-image:{image}", f"builder:{builder.resolve()}")):
    build_image()
    with user.transaction() as locked:
        save_fingerprint(locked)
```

Lease identity excludes plugin ID, so different plugins contend on the same exact
name. Acquire leases before state transactions. Acquiring a lease from inside a
transaction is rejected; nested leases and transactions are also rejected. Lock
files persist to avoid file-replacement races and use non-inheritable advisory-lock
handles.

Leases coordinate only cooperating Engulf processes. External resources still need
ownership markers and recovery journals.
