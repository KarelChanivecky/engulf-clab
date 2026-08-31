# Plugin Instructions

This package publishes the call-scoped immutable source topology and deferred
mutation API. Do not write topology files here.

- Keep plugin ID `engulf_clab.lab_parser`, priority `100`, and context ID
  `engulf_clab.topology.session` stable for dependent distributions.
- Parse and publish topology sessions only for deploy with a local filesystem
  topology. For destroy by source, prefer its retained writer topology when it
  exists; otherwise contribute the single non-writer source for implicit
  selection. Resolve a unique retained topology for name selection and preserve
  all-labs selection.
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
`derived_topology_path()` deterministically maps a resolved source topology to
the hidden same-directory path retained by the writer. Destroy analysis uses
that path when it exists, replacing an explicit source topology option or
supplying it for implicit selection.

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
may create missing mapping parents. Addition requires a missing mapping key or
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

Use `./build.sh` in this directory for a distribution build, and `git diff --check`
before committing. Never run real deploy/destroy, Docker builds, Git clones, or
privileged MCP installation as part of validation.
