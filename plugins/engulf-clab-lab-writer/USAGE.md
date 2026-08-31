# engulf-clab-lab-writer

Renders feature-plugin mutations into a retained derived topology for deploy. It has
no lab-facing YAML, environment variables, or options.

Install it whenever a plugin uses `engulf-clab-lab-parser` to mutate YAML:
through that feature plugin, directly with `python -m pip install
engulf-clab-lab-writer`, or through `engulf-clab-all-plugins`, which installs
both packages.

The original topology is never edited. The generated file is named
`.engulf-clab-lab-<source-id>.clab.yml` and lives beside the source, so relative
paths keep the same meaning. The source-derived identifier is deterministic:
redeploy atomically replaces the same file, while different source topologies
use different paths. Shared resource leases remain the responsibility of the
feature plugins that need them.

During side-effect-free deploy analysis the writer locates every token it will
need; publication itself is atomic. YAML is first written to a unique staged
file in the same directory and renamed only after serialization succeeds. A
failure removes the staged file and prevents Containerlab from running. The
derived file remains after deploy so the `clab-topo-file` container label keeps
pointing to a readable topology containing the actual mutated nodes and
management network. It is retained after failed or interrupted deploy too,
because Containerlab may already have created partial host state. Destroy is
routed through this retained file and removes it only after successful cleanup.
The parser ignores these files during ordinary implicit source selection.

The parser has already expanded Containerlab environment expressions before
plugins inspect the topology. The writer escapes dollar signs in rendered
string keys and values so Containerlab's own substitution stage preserves that
result instead of expanding it a second time. This also keeps escaped dollars,
unresolved placeholders, and literal `$` characters inside environment values
stable through the generated file.

The writer requires the `engulf_clab.topology.session` context and must remain
after every topology mutator in preprocessing; otherwise later deferred
operations would not reach Containerlab. Missing, ambiguous, duplicate, stdin,
and URL topologies are not supported.

The writer never deletes or renames the source or recursively cleans unrelated
files. It has no environment variables or dynamic help. If Containerlab
diagnostics mention a generated path, keep it until the lab and its host
resources have been destroyed; deleting it early forces Containerlab into its
incomplete file-less fallback. After successful destroy the writer removes only
the retained path passed to Containerlab.
