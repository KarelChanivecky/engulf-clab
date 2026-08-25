# engulf-clab-lab-parser

Provides the local topology selection and shared mutation session used by
topology-aware plugins. Lab authors configure no parser-specific YAML, labels,
environment variables, or options.

Install it through a topology-aware feature plugin, directly with `python -m pip
install engulf-clab-lab-parser`, or through `engulf-clab-all-plugins`.

For deploy, eclab loads one local YAML source and lets feature plugins record
changes against an immutable original. The writer later applies those changes
to a temporary topology; the selected source file is never modified.

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

Hidden `.engulf-clab-lab-*.clab.yml` writer outputs are ignored during implicit
selection. For destroy, an explicit topology or `--name` is left unchanged. If
neither is supplied and one source exists, eclab passes that source explicitly
so a stale generated file cannot make Containerlab selection ambiguous. With
zero or multiple sources, Containerlab retains control of the destroy
diagnostic.

YAML is loaded safely and must have a top-level mapping. Containerlab remains
responsible for the base schema and semantic validation; each feature plugin
validates the fields it consumes. Mutation conflicts are reported before the
temporary topology is published.
