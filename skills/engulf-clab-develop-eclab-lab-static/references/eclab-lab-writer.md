# engulf-clab-lab-writer

Renders feature-plugin mutations into a temporary topology for deploy. It has
no lab-facing YAML, environment variables, or options.

Install it whenever a plugin uses `engulf-clab-lab-parser` to mutate YAML:
through that feature plugin, directly with `python -m pip install
engulf-clab-lab-writer`, or through `engulf-clab-all-plugins`, which installs
both packages.

The original topology is never edited. The generated file is named
`.engulf-clab-lab-<random>.clab.yml` and lives beside the source, so relative
paths keep the same meaning. The random component avoids collisions between
concurrent calls; shared resource leases remain the responsibility of the
feature plugins that need them. Eclab passes that file to Containerlab with
`-t`, then removes it after the call regardless of the wrapped result.

During side-effect-free deploy analysis the writer locates every token it will
need; publication itself is atomic. YAML is first written to a unique staged
file in the same directory and renamed only after serialization succeeds. A
failure removes the staged file and prevents Containerlab from running. Before
writing a fresh temporary topology, `prepare_call()` sweeps any leftover
`.engulf-clab-lab-*.clab.yml` files from the topology directory after an earlier
process crash, and `after_call()` removes the generated file. The parser also
ignores these files during implicit topology selection.

The writer requires the `engulf_clab.topology.session` context and must remain
after every topology mutator in preprocessing; otherwise later deferred
operations would not reach Containerlab. Missing, ambiguous, duplicate, stdin,
and URL topologies are not supported.

The writer never deletes or renames the source, recursively cleans unrelated
files, or retains user/workspace state. It has no environment variables, dynamic
help, or destroy behavior. If Containerlab diagnostics mention a generated path,
use the reported owner and path from the accompanying materialization conflict
to reconcile mutators; normal cleanup may remove that temporary file immediately
after the call. After an abrupt process kill, confirm any hidden writer file is inactive
before removing it manually.
