# Plugin Instructions

This package publishes the call-scoped immutable source topology and deferred
mutation API. Do not write topology files here.

- Keep plugin ID `engulf_clab.lab_parser`, priority `100`, and context ID
  `engulf_clab.topology.session` stable for dependent distributions.
- Parse and publish topology sessions only for deploy or single-source redeploy
  with a local filesystem topology. Preserve native `redeploy --all` and
  name-only handling. For destroy by source, prefer its retained writer topology when it
  exists; otherwise contribute the single non-writer source for implicit
  selection. Resolve a unique retained topology for name selection and preserve
  all-labs selection. Route the lab-reading commands that search for a topology
  the same way, and leave commands that act on every lab alone.
  Keep all selection and parse validation side-effect free; publish the session
  only in preparation.
- Preserve all supported Containerlab topology option forms and deterministic
  one-file discovery. Reject ambiguous/missing selections instead of guessing.
- Expand Containerlab shell-style environment expressions from the effective
  call environment before safe-loading YAML, then require a top-level mapping.
  Preserve unset expressions and escaped dollars exactly as Containerlab does.
  Do not perform feature-specific mutation or full semantic validation here.
- Keep the recursively frozen original, deep-copy access, copied operation
  values, owner attribution, path validation, delete precedence, conflict
  detection, and deterministic materialization phases.
- Do not expose mutable internal source data or retain callback-bound API/session
  handles beyond an invocation.
- This distribution declares `engulf_clab.schema` as a hard packaging-metadata
  dependency, positioned after the parser in preprocessing so schema registration
  is complete before terminal compilation. Engulf derives the runtime dependency
  from that entry point; do not declare `plugin_dependencies` in Python.
- Treat public imports, context IDs, path/operation semantics, and state-free
  behavior as a shared compatibility contract. Update this contributor API
  reference and tests together; keep `USAGE.md` limited to lab-visible source
  selection and immutability.
- A mutator declares a hard preprocessing dependency on
  `engulf_clab.lab_parser`, reads `engulf_clab.topology.session`, and declares
  the writer after itself — for example an image-graph contributor consuming
  materialized node environment controls.
- Run parser tests plus writer and every direct topology-mutator suite after a
  contract change. Use temporary YAML only; never deploy. Preserve schema
  registration before the generator's terminal preprocessing position. Base
  topology syntax remains owned by the exact Containerlab schema composed by the
  terminal generator, not by this package.

## Public mutation API

`effective_nodes(document)` returns a tuple of recursively immutable
`EffectiveNode` snapshots. `session.effective_nodes()` resolves a fresh
`materialize()` result, including previous deferred edits. Use this API for
inherited controls instead of merging definitions in a consumer.

Each node exposes `name`, `data`, `origin(*field)`, and
`declared_origins(*field)`. Fields use relative tuple paths such as
`("env", "FEATURE")`. A `FieldOrigin` carries `level`, `name`, and the absolute
YAML `path`. Winning origins describe values actually returned; declaration
origins also retain shadowed and empty/null declarations, in precedence order.
Inputs and snapshots never share mutable maps or lists.

Kind selection follows Go's finite chain: node kind, the explicitly selected
node group's kind, the defaults group's kind, then defaults kind. Group
selection uses node group, selected kind's group, then defaults group. Resolve
these selectors before applying defaults < kind < group < node.
As in Go, a null node definition uses defaults group directly.

String fields inherit on missing, empty, or null values. String maps (`env`,
`labels`, `sysctls`, `tmpfs`) merge by key, including empty-string overrides;
null entries become empty strings and native booleans become boolean strings.
YAML decoding preserves scalar spellings, so `yes` remains `"yes"` and `False`
remains `"False"`. Programmatically supplied booleans use lowercase spellings.
Native boolean fields retain false; null inherits. Additive native string lists
merge in source order with duplicates removed; empty lists do not clear them.
Whole-object declarations such as DNS replace the less-specific object.
Management addresses and aliases are node-only. This is a declaration view;
native kind runtime defaults, env-file loading, bind-path/target normalization,
and lifecycle structure compilation remain Containerlab's responsibility.

`topology_declarations(document)` enumerates immutable `TopologyDeclaration`
values for all defaults, kinds, groups, and nodes, including unused definitions.
Use `field_origin(*field).path` for redaction: inspecting only winning effective
values would leak shadowed declarations into an archive. Malformed definitions
are left to consumers/native validation; effective-node resolution rejects
malformed selected definitions. No string or object is a special remove marker.

`parse_topology_yaml(source)` safely decodes topology YAML with Go string-field
spellings but performs no environment expansion. Freeze uses it to preserve
unresolved recipient expressions and avoid embedding private env-file values.

Consumers obtain a plugin-owned editor from the published topology session:

```python
from engulf_clab_lab_parser import editor

mutation = editor(api, "com.example.plugin")
mutation.modify(("topology", "nodes", "router", "license"), "/path/license.lic")
mutation.delete(("topology", "nodes", "wan", "labels", "ECLAB_DHCP_WAN"))
mutation.add(("topology", "nodes", "client", "labels", "role"), "client")
```

`topology_path_from_args()` recognizes separate and equals forms of `-t`,
`--topo`, and `--topology`. `load_topology()` expands the effective call
environment in the raw source before safe YAML loading and requires a top-level
mapping. Its optional environment mapping makes callback behavior explicit and
tests deterministic; omitting it uses the current process environment.
`is_topology_mutation_command()` is the shared command gate for every mutator:
it accepts deploy and single-source redeploy while leaving `redeploy --all`
and name-only redeploy to Containerlab. Consumers must use it instead of
maintaining their own command set.
`derived_topology_path()` deterministically maps a resolved source topology to
the hidden same-directory path retained by the writer. Destroy analysis uses
that path when it exists, replacing an explicit source topology option or
supplying it for implicit selection. `_LAB_COMMANDS` names the read-only
subcommands that supply it the same way, including replacing an explicit source
topology so Containerlab sees the deployed rather than build-time node set. Add
a subcommand there only after confirming it searches the working directory for
a topology rather than acting on every lab, and that the deploy pipeline it
would bypass is not needed.

`TopologySession.path` is the resolved source; `original` is a recursively
frozen mapping/tuple view for immutable inspection; `original_document()`
returns a deep mutable copy; `editor(owner)` attributes deferred operations to a
nonempty plugin ID; and `materialize()` returns a fresh document with all
operations resolved. Do not retain the session, editor, or invocation
API beyond the active callback.

A `YamlPath` is a nonempty tuple of string mapping keys and integer list
indexes, for example `("topology", "nodes", "router", "env", "FEATURE")`; any
other element type is rejected. An invalid mapping/list transition or an
out-of-range index fails before the writer publishes a derived topology.
Deletion ignores a missing target, and deleting a parent suppresses every
descendant add/modify regardless of plugin order. Modification replaces a mapping value or existing list index and
may create missing or null mapping parents. Addition requires a missing mapping key or
inserts at an index from zero through the current list length. Values are copied
when recorded. Different operation kinds or values at one path report both
owners; identical modifications are accepted, while duplicate additions still
fail add-only materialization.

Materialization applies deepest deletions first, then modifications, then
additions, with parent paths before children in the latter phases. Consumers
should validate against `original_document()` during analysis where possible
and record changes only during preparation. A consumer that needs earlier
deferred changes may call `materialize()` without writing a file.

## Validation

Run the narrowest checks that exercise the changed boundary:

```bash
.venv/bin/python -m compileall -q plugins/engulf-clab-lab-parser/src
.venv/bin/python -m pytest -q plugins/engulf-clab-lab-parser/tests
make check-skill
```

This package is a shared API: after a contract change also run the writer suite
and every direct topology-mutator suite (`engulf-clab-wan`,
`engulf-clab-license-pool`, `engulf-clab-dockerfile-build`,
`engulf-clab-containers`).

Run `make build-<package>` for a distribution build (or `make build` for
every distribution), and `git diff --check` before committing. Never run
real deploy/destroy, Docker builds, Git clones, or
privileged MCP installation as part of validation.
