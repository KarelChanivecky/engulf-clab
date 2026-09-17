# engulf-clab-lab-parser

Provides the local topology selection and shared mutation session used by
topology-aware plugins. Lab authors configure no parser-specific YAML or
labels; the only author-facing inputs are the optional private env file
described below and its `ECLAB_ENV_FILE` override.

Install it through a topology-aware feature plugin, directly with `python -m pip
install engulf-clab-lab-parser`, or through `engulf-clab-all-plugins`.

For deploy and single-source redeploy, eclab loads one local YAML source and lets feature plugins record
changes against an immutable original. Before YAML decoding, the parser eagerly
expands environment expressions from the effective Containerlab call
environment. Every analyzer and mutator therefore sees the same rendered
values, including image provisioning plugins that run before Containerlab. The
writer later applies plugin changes to a temporary topology; the selected
source file is never modified.

The supported syntax matches Containerlab: `$VAR`, `${VAR}`, `${VAR-default}`,
`${VAR:-default}`, `${VAR=default}`, `${VAR:=default}`, `${VAR+alternative}`,
`${VAR:+alternative}`, and `$$` escaping. As in Containerlab, unset plain
variables remain recognizable instead of silently becoming empty, while a
defaulted expression such as `${FGT_IMAGE:=fgt:8.0.1.0203}` becomes a literal
before downstream processing. Expansion occurs in the raw YAML, so quote an
expression when its rendered value must remain a YAML string rather than a
boolean, number, or null.

## Inherited node settings

Feature plugins use a shared immutable node view with Containerlab precedence:
`defaults < kind < group < node`. Kind/group selection also honors their native
fallbacks. Standard YAML remains governed by the upstream
[Containerlab schema](https://github.com/srl-labs/containerlab/blob/main/schemas/clab.schema.json).

| Declaration | String fields such as image/network-mode | An individual env value | Native boolean fields |
| --- | --- | --- | --- |
| Missing key | Inherit | Inherit | Inherit |
| Empty string | Inherit | Override with empty string | Invalid native boolean |
| String `"false"` | Literal string | Literal string; boolean consumers interpret it | Invalid native boolean |
| Native `false` | String `"false"` | String `"false"` | Override with false |
| Null | Inherit | Override with empty string | Inherit |
| `"remove"` | Literal string | Literal string | Invalid native boolean |

There is no explicit removal marker. An empty or null entire `env` mapping
inherits its keys; an empty or null value inside that mapping overrides one key.
Feature validators still enforce their path, reference, and enum contracts.
Quote strings when their exact spelling matters; YAML string-map scalars retain
their source spelling, including `yes`, `False`, and numeric values.

## Lab environment file

A topology may sit beside a private env file that supplies the variables it
expands from. The name comes from the topology filename with its suffix
removed, so `all-features.clab.yml` pairs with `all-features.env`, and bare
`clab.yml` or `topology.yaml` pair with `clab.env` or `topology.env`. The name
is deliberately not the topology's `name:` field: the file has to be found
before the document can be expanded, and the two often differ.

These values are read only to expand the topology. Unlike Containerlab's
`env-files:`, they never become node environment, so nothing in the file
reaches a container unless the topology references it. Wherever the topology
does reference one, the resolved value lands there like any other expansion.

The process environment wins over the file, so `FGT_IMAGE=other eclab deploy`
still overrides it. A missing file is not an error, because the pairing is a
convention rather than a declaration. Set `ECLAB_ENV_FILE` to one or more
paths, separated by the platform path separator, to replace the convention with
an explicit list; files named that way must exist.

Accepted syntax is the assignment subset of dotenv: blank lines and `#`
comments are skipped, a leading `export ` is allowed, and values may be
single-quoted (literal), double-quoted (with `\n`, `\t`, `\\` and `\"`
unescaped), or bare with a trailing ` #` comment stripped. Values are never
interpolated against each other or the environment; expansion belongs to the
topology.

`eclab freeze` excludes `*.env` from the archive it builds and records the
omission in `FREEZE-WARNINGS.txt`. A frozen topology therefore keeps its
unresolved references, and whoever defrosts it supplies their own file, the
same way they supply their own licenses.

## Topology selection

Separate and equals forms of `-t`, `--topo`, and `--topology` are supported.
More than one topology option is rejected. An explicit path expands `~` and
resolves from the invocation working directory. Without an option, the selected
directory must contain exactly one source matching:

```text
*.clab.yml
*.clab.yaml
clab.yml
clab.yaml
topology.yml
topology.yaml
```

For deploy and other filesystem-mutating features, zero or multiple matches
require an explicit path. URL and stdin topologies are valid Containerlab
inputs but cannot use this mutation pipeline.

Hidden `.engulf-clab-lab-*.clab.yml` writer outputs are ignored during ordinary
implicit source selection. For destroy by source, eclab prefers the stable
derived topology retained from deploy, including when the original source was
passed explicitly. That preserves the actual mutated node and management
configuration needed for complete host cleanup. If no retained file exists,
implicit destroy passes the single source explicitly and explicit source
selection is unchanged. A name that uniquely matches a retained topology is
routed through that file; otherwise name and all-labs selection remain under
Containerlab's label-based handling. With zero or multiple sources Containerlab
retains control of the diagnostic.

`inspect`, `graph`, and `save` are routed the same way, because the retained
file otherwise makes Containerlab's own implicit search ambiguous and no lab
can be reached from its own directory. An explicit source topology is replaced
with its retained deploy topology when that file exists, so inspection uses the
actual deployed node set; an explicit retained topology, `--name`, and `--all`
remain untouched. `exec` and `events` are not routed: without a topology they
act on every lab on the host rather than searching for one. A single-source
`redeploy` rebuilds the derived topology through the same parser and mutator
pipeline as `deploy`. `redeploy --all` and name-only redeploy remain under
Containerlab's native handling because they do not identify one authoritative
source topology.

YAML is loaded safely and must have a top-level mapping. Containerlab remains
responsible for the base schema and semantic validation; each feature plugin
validates the fields it consumes. Mutation conflicts are reported before the
temporary topology is published.
