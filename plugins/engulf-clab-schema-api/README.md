# engulf-clab schema API

`engulf-clab-schema-api` is the stable typed contract used by Engulf plugins to
describe their installed commands, environment variables, topology controls,
use cases, rejection guidance, and packaged references. It performs no plugin
discovery, schema compilation, network access, or installation.

Create one module-level `PluginSchema`, declare the schema generator as an
Engulf dependency positioned after the contributor, union `SCHEMA_CONTEXTS`
into both context declarations, and call `record_plugin_schema()` at the start
of `before_goal()`. The helper stores an immutable snapshot in invocation
context; callback API objects are never retained.

Every option has a short one-line explanation. Put detailed behavior in
package resources and add them with `refer()`. Resource paths are relative to
the import package and must also be present in the built wheel.

## Builder signatures

`PluginSchema(plugin_id: str, *, package: str)` creates a mutable import-time
builder. `plugin_id` is the exact lowercase, dot-qualified Engulf plugin ID.
`package` is the import package used to resolve its distribution metadata and
packaged references. Every mutator returns the same builder, so declarations
may be chained.

```python
add_command(
    name: str,
    explanation: str,
    *,
    aliases: tuple[str, ...] = (),
    deprecated: bool = False,
    replacement: str | None = None,
) -> PluginSchema
```

Declares a wrapper-owned command token. `{short_product}` is expanded from
callback-bound application metadata in the command, aliases, and replacement.

```python
add_cli_argument(
    command: str,
    name: str,
    explanation: str,
    *,
    values: ValueSpec,
    required: bool = True,
    repeatable: bool = False,
    default: JsonValue | UnsetType = UNSET,
    deprecated: bool = False,
    replacement: str | None = None,
) -> PluginSchema
```

Declares a positional argument owned by a previously declared command.
`repeatable=True` means the argument may occur more than once.

```python
add_cli_flag(
    names: str | tuple[str, ...],
    explanation: str,
    *,
    command: str | None = None,
    values: ValueSpec | None = None,
    required: bool = False,
    repeatable: bool = False,
    default: JsonValue | UnsetType = UNSET,
    deprecated: bool = False,
    replacement: str | None = None,
) -> PluginSchema
```

Declares one flag or an alias tuple whose first item is canonical. With
`command=None` it is wrapper-global; otherwise it is scoped to a previously
declared command. `values=None` describes a boolean switch.

```python
add_runtime_var(
    name: str,
    explanation: str,
    *,
    values: ValueSpec,
    default: JsonValue | UnsetType = UNSET,
    required: bool = False,
    deprecated: bool = False,
    replacement: str | None = None,
) -> PluginSchema
```

Declares an invocation environment variable. One wildcard is allowed only in
the final name portion, for example `ECLAB_LICENSE_*`.

The three topology-property methods have the same signature:

```python
add_root_prop(
    path: str,
    explanation: str,
    *,
    values: ValueSpec,
    default: JsonValue | UnsetType = UNSET,
    required: bool = False,
    deprecated: bool = False,
    replacement: str | None = None,
) -> PluginSchema

add_node_prop(...) -> PluginSchema
add_link_prop(...) -> PluginSchema
```

They declare dotted paths relative to the topology root, each explicit node,
or each link. Escape a literal dot as `\.`. One wildcard is allowed only in
the final segment.

```python
add_node_var(
    name: str,
    explanation: str,
    *,
    values: ValueSpec,
    default: JsonValue | UnsetType = UNSET,
    required: bool = False,
    deprecated: bool = False,
    replacement: str | None = None,
) -> PluginSchema
```

Declares a variable inside a node's Containerlab `env` object. A final wildcard
describes a family such as `ECLAB_DOCKER_VAR_*`.

```python
annotate(
    subject: str,
    *,
    commands: tuple[str, ...] = (),
    lifecycle: tuple[LifecycleStage, ...] = (),
    requires: tuple[str, ...] = (),
    conflicts_with: tuple[str, ...] = (),
    implies: tuple[str, ...] = (),
    path_base: PathBase | None = None,
    privilege: Privilege | None = None,
    host_tools: tuple[str, ...] = (),
    shared_with: tuple[str, ...] = (),
    examples: tuple[str, ...] = (),
) -> PluginSchema

require_host_tool(
    name: str,
    explanation: str,
    *,
    commands: tuple[str, ...] = (),
) -> PluginSchema

require_privilege(
    privilege: Privilege,
    explanation: str,
    *,
    commands: tuple[str, ...] = (),
) -> PluginSchema

order(
    stage: LifecycleStage,
    explanation: str,
    *,
    after: tuple[str, ...] = (),
    before: tuple[str, ...] = (),
) -> PluginSchema

route(task: str, reference: str, explanation: str) -> PluginSchema
add_node_kind(
    kind: str,
    explanation: str,
    *,
    reference: str,
) -> PluginSchema
use_case(explanation: str) -> PluginSchema
reject(reason: str) -> PluginSchema
refer(path: str | PurePosixPath, *, title: str | None = None) -> PluginSchema
```

`annotate()` adds operational semantics to one declared canonical option or
alias. `commands` scopes it; `lifecycle` says when it is read; `requires`,
`conflicts_with`, and `implies` record relationships; `path_base` defines
relative-path resolution; `privilege` and `host_tools` expose host needs;
`shared_with` identifies another owning plugin; and `examples` supplies safe
one-line values or snippets.

`require_host_tool()` and `require_privilege()` describe plugin-level runtime
requirements, optionally scoped to commands. `order()` records a lifecycle
edge to other exact plugin IDs and requires at least one `after` or `before`
value. `route()` maps a lowercase task token to a resource also packaged by
`refer()`; an unresolved route makes snapshot creation fail.

`add_node_kind()` augments an exact kind discovered from the selected
Containerlab source. It does not invent a new valid kind or copy Containerlab's
structural schema. Its detailed edition-specific guidance must name a resource
also packaged through `refer()`; compilation fails when the selected
Containerlab source does not advertise the kind.

`use_case()` tells the skill when the plugin is a fit. `reject()` records a
boundary or prohibited assumption. `refer()` is repeatable and snapshots a
package-relative Markdown, text, JSON, or YAML resource when the invocation
runs; absolute paths, traversal, case-colliding duplicates, and oversized
resources are rejected.

`publish_containerlab_source()` and `publish_vrnetlab_source()` may publish
immutable source hints when another plugin has already resolved a checkout or
repository revision. Without a vrnetlab hint, the generator follows
`VRNETLAB_DIR`, the managed checkout, `VRNETLAB_REPO`/`VRNETLAB_VERSION`, then
the configured default repository.
The hint's `resolved` field is false for an early selection and true only after
the owning ensure plugin has selected the concrete checkout or binary. The
generator still resolves repository revisions to exact commits before writing
the manifest.

`ValueSpec` is either one `ValueType` or a nonempty tuple containing accepted
types, literal JSON scalars, or `ExplainedValue(value, explanation)` entries.
Literal and explained literal entries form a closed set when no `ValueType` is
present. Explained literals accompanying one or more `ValueType` members are
non-exclusive recognized values: they are described in the compact agent YAML
without narrowing the full validation schema. Bare literal values and
`ValueType` members cannot be mixed.

Available types cover strings, numbers, booleans, arrays, objects, null, paths,
URIs, IP addresses and CIDRs, UUIDs, image references, and environment names.
Every explained value has its own one-line explanation of at most 240
characters. `default` is omitted unless explicitly supplied; `replacement` is
valid only when `deprecated=True`.

For example, a container collection can advertise packaged choices while
continuing to accept every valid Containerlab image reference:

```python
values=(
    ValueType.IMAGE_REFERENCE,
    ExplainedValue("example/helper", "Use the packaged helper container."),
)
```

Every option and relationship explanation, use case, rejection reason,
requirement, example, and reference title is required to be nonempty, one line,
free of control characters, and at most 240 characters. Detailed syntax,
lifecycle, security, and troubleshooting material belongs in `refer()`
resources.

The API is intentionally declarative. Runtime analyzers remain authoritative
for conditional validation, cross-field rules, host work, and side effects.
