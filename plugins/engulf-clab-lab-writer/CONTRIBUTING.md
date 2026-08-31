# Plugin Instructions

This collector runs after topology mutators, writes only a temporary derived
YAML file, and always attempts cleanup in `after_call()`.

- Keep plugin ID `engulf_clab.lab_writer`, priority `-100`, parser dependency,
  and topology-context read stable.
- Activate only for deploy. During analysis, remove all source topology option
  tokens and contribute exactly one generated `-t` pair before the separator.
- Place the target beside the source topology with an unguessable
  `.engulf-clab-lab-*.clab.yml` name so relative paths retain source semantics.
- In preparation, materialize once, write a same-directory staged file, and
  publish atomically. Escape every rendered dollar before serialization so
  Containerlab's own environment pass cannot expand the topology a second
  time. Remove the staged file on every exception.
- In postprocessing, unlink only a path recognizable as this invocation's
  generated topology. Tolerate missing files and preserve the wrapped outcome.
- Never write, rename, or delete the selected source topology. Do not own feature
  mutation logic, state, leases, or runtime help.
- Keep this contributor reference's argv/integration contract and `USAGE.md`'s
  user-visible file/cleanup behavior synchronized.
- Run writer plus parser and direct mutator tests. Use temporary files; never run
  Containerlab. Keep schema registration separate from temporary-file work.

## Integration contract

During deploy analysis, remove every token belonging to the selected `-t`,
`--topo`, or `--topology` option and contribute one replacement
`-t <generated-path>` pair before any `--` separator. Use the parser's source
selection; do not independently accept duplicate, ambiguous, stdin, or URL
topologies.

A mutator depends on the parser before itself and the writer after itself,
records operations under its exact plugin ID, and never writes a competing
derived topology. The writer materializes once during preparation, doubles
dollar signs in every string key/value to preserve the parser's already
rendered values through Containerlab's substitution pass, preserves YAML key
order where possible, and owns only its recognizable generated and staged
paths. Feature-specific state, leases, validation, and mutation logic remain
with the mutator.

## Validation

Run the narrowest checks that exercise the changed boundary:

```bash
.venv/bin/python -m compileall -q plugins/engulf-clab-lab-writer/src
.venv/bin/python -m pytest -q plugins/engulf-clab-lab-writer/tests
make check-skill
```

After a contract change also run `engulf-clab-lab-parser` and every direct
topology-mutator suite.

Use `./build.sh` in this directory for a distribution build, and `git diff --check`
before committing. Never run real deploy/destroy, Docker builds, Git clones, or
privileged MCP installation as part of validation.
