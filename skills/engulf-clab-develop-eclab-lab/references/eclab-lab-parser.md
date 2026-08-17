# engulf-clab-lab-parser

Provides the shared topology session used by plugins that read or defer changes
to a Containerlab YAML file. Install it as a dependency of a topology-aware
plugin; `engulf-clab-all-plugins` installs it automatically.

It is infrastructure for plugin authors. Lab authors do not add parser-specific
YAML, labels, environment variables, or command options.

## Contents

- [Topology selection](#topology-selection)
- [Session contract](#session-contract)
- [YAML paths and operations](#yaml-paths-and-operations)
- [Plugin integration](#plugin-integration)

For `deploy`, the plugin loads the selected `-t` / `--topo` / `--topology` YAML
once and publishes an immutable original document plus a mutation editor in
Engulf context. It has no YAML extension fields and no environment variables for
lab authors.

Plugin authors use the session through `engulf_clab_lab_parser`:

```python
from engulf_clab_lab_parser import editor

mutation = editor(api, "com.example.plugin")
mutation.modify(("topology", "nodes", "router", "license"), "/path/license.lic")
mutation.delete(("topology", "nodes", "wan", "labels", "ECLAB_DHCP_WAN"))
mutation.add(("topology", "nodes", "client", "labels", "role"), "client")
```

Mutations are deferred: chained plugins continue to see the original topology.
The collector plugin applies them later. Deletes override descendant modifications
and additions; modifications and additions create missing mapping parents; list
additions insert at the supplied integer index. Conflicting modifications at the
same path are rejected.

## Topology selection

`topology_path_from_args()` recognizes separate and equals forms of `-t`,
`--topo`, and `--topology`. More than one topology option is rejected. An
explicit path is expanded and resolved from the invocation working directory.

Without an option, the selected directory must contain exactly one recognized
file across these patterns:

```text
*.clab.yml
*.clab.yaml
clab.yml
clab.yaml
topology.yml
topology.yaml
```

Zero or multiple matches require an explicit option. URL and stdin topologies
are valid Containerlab features but cannot participate in this filesystem-based
mutation pipeline; topology-mutating eclab features require one local file.

`load_topology()` uses safe YAML loading and requires a top-level mapping. Base
Containerlab schema/semantic validation remains Containerlab's responsibility;
feature plugins validate the portions they consume.

## Session contract

For deploy, `engulf_clab.lab_parser` validates selection/parsing during
side-effect-free analysis. During preparation it publishes one `TopologySession`
to context `engulf_clab.topology.session`:

| Member | Meaning |
| --- | --- |
| `path` | Resolved selected source path. |
| `original` | Recursively frozen mapping/tuple view for immutable inspection. |
| `original_document()` | Fresh deep mutable copy of the unmodified source document. |
| `editor(owner)` | Editor that attributes later operations to a nonempty plugin ID. |
| `materialize()` | Fresh deep copy with all recorded operations resolved in deterministic phases. |

The convenience `editor(api, owner)` requires the active context and returns a
plugin-owned editor. Do not retain a session/editor or invocation API beyond its
callback.

## YAML paths and operations

A `YamlPath` is a nonempty tuple of string mapping keys and integer list indexes,
for example `("topology", "nodes", "router", "env", "FEATURE")`.

- `delete(path)` ignores a missing target. Parent deletion suppresses every
  descendant add/modify regardless of plugin order.
- `modify(path, value)` replaces a mapping value or existing list index. Missing
  mapping parents are created.
- `add(path, value)` requires a missing mapping key or inserts at list index
  `0..len(list)`. Missing mapping parents are created.
- Values are copied when recorded and the source document is never returned for
  in-place mutation.
- Different operations or values at the same path identify both owners in a
  conflict error. Each added path should have one owner; duplicate additions
  still violate add-only semantics when materialized.

Materialization applies deepest deletes first, then modifications, then
additions, with shorter parent paths before deeper child paths in each phase.
An invalid mapping/list transition or out-of-range index fails before the writer
publishes a derived topology.

## Plugin integration

A mutator declares a hard preprocessing dependency on
`engulf_clab.lab_parser`, reads `engulf_clab.topology.session`, and declares the
writer after itself. Validate proposed changes against `original_document()` in
analysis when possible, then record them in preparation. A plugin that needs
earlier deferred changes—such as the Dockerfile builder consuming collection
recipes—may call `materialize()` during preparation without writing a file.

Run parser tests after changing selection, freezing, path resolution, operation
precedence, conflicts, copying, or materialization. Run every mutator and writer
suite after a public session/operation behavior change.
