# engulf-clab-lab-writer

Renders deferred topology mutations into a temporary YAML file and replaces the
topology argument passed to Containerlab for `deploy`. Install it whenever a
plugin uses `engulf-clab-lab-parser` to mutate YAML; `engulf-clab-all-plugins` installs
both packages.

It has no user-facing YAML fields or environment variables. The original lab
file is never edited. During deploy, the collector writes a temporary
`.engulf-clab-lab-*.clab.yml` file beside the source topology, passes it with
`-t`, and removes it after the wrapped call. Keeping both files in the same
directory preserves Containerlab's resolution of relative paths. Plugins before
the collector record operations in the shared topology session; it resolves
delete precedence and applies modifications before additions.

This package is infrastructure for plugin authors, not a feature that lab
authors configure directly.

## Effective argument behavior

During side-effect-free deploy analysis, the writer locates every token that
belongs to the selected `-t`, `--topo`, or `--topology` option, contributes
removals for those indexes, and contributes one replacement
`-t <temporary-path>` before any `--` separator. It relies on the parser's
selection rules, so missing, ambiguous, duplicate, stdin, and URL topologies are
not supported by the filesystem mutation pipeline.

The target name has the form:

```text
.engulf-clab-lab-<random-hex>.clab.yml
```

It lives beside the original topology. The random name avoids collisions
between concurrent calls, while shared resource leases remain the responsibility
of the feature plugins that need them.

## Materialization and cleanup

During preparation, the writer requires context `engulf_clab.topology.session`,
calls `TopologySession.materialize()`, and writes YAML with original key order
preserved where possible. It first writes a unique staged file in the same
directory and atomically renames it to the path already contributed to the
effective argv. A serialization or write failure removes the staged file and
prevents Containerlab from running.

`after_call()` identifies only the writer-generated path in effective arguments
and unlinks it if present, regardless of the wrapped outcome. It never deletes
the source topology and does not recursively clean unrelated files.

Before writing a fresh temp topology, `prepare_call()` sweeps any leftover
`.engulf-clab-lab-*.clab.yml` files from the topology directory — the residue
of a prior deploy whose `after_call()` could not run (process kill, crash). This
keeps the directory tidy and the parser's glob-based topology selection
unambiguous. The parser also ignores files with the `.engulf-clab-lab-` prefix
when globbing for the active topology, so a stale temp file can never shadow or
duplicate the source lab file. If the process is killed so abruptly that
neither `after_call()` nor a subsequent `prepare_call()` can run, a hidden
`.engulf-clab-lab-*.clab.yml` may remain beside the source; confirm it is not
active before removing it manually.

The writer has no user/workspace state, environment variables, dynamic help, or
destroy behavior. It must remain after every topology mutator in preprocessing;
otherwise later deferred operations would not reach Containerlab.

## Plugin integration and troubleshooting

A mutating plugin should depend on the parser before itself and the writer after
itself, record operations under its exact plugin ID, and never write its own
derived topology. When materialization fails, use the reported owner/path
conflict to reconcile mutators. When Containerlab reports a generated topology
path, inspect the plugin diagnostics during the active call; normal cleanup may
remove that file immediately afterward.

Run parser and writer tests together after changing option replacement,
operation resolution, file placement, YAML serialization, atomic publication,
or cleanup.
