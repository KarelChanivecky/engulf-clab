# engulf-clab-lab-parser

Provides the local topology selection and shared mutation session used by
topology-aware plugins. Lab authors configure no parser-specific YAML, labels,
environment variables, or options.

Install it through a topology-aware feature plugin, directly with `python -m pip
install engulf-clab-lab-parser`, or through `engulf-clab-all-plugins`.

For deploy, eclab loads one local YAML source and lets feature plugins record
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
can be reached from its own directory. They keep an explicit topology, a
`--name`, or `--all` untouched. `exec` and `events` are not routed: without a
topology they act on every lab on the host rather than searching for one.
`redeploy` is not routed either, since the pipeline that derives the topology
runs only for deploy.

YAML is loaded safely and must have a top-level mapping. Containerlab remains
responsible for the base schema and semantic validation; each feature plugin
validates the fields it consumes. Mutation conflicts are reported before the
temporary topology is published.
