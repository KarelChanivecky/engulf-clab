# Plugin Instructions

This collector runs after topology mutators and retains one stable derived YAML
file until Containerlab successfully destroys the lab.

- Keep plugin ID `engulf_clab.lab_writer`, priority `-100`, parser dependency,
  and topology-context read stable.
- Declare parser and schema ordering only in the package dependency entry-point
  group; never restore a code-level `plugin_dependencies` declaration.
- Activate only for deploy. During analysis, remove all source topology option
  tokens and contribute exactly one generated `-t` pair before the separator.
- Place the target beside the source topology at the deterministic
  `.engulf-clab-lab-<source-id>.clab.yml` path so relative paths retain source
  semantics and Containerlab labels keep a usable recovery topology.
- In preparation, materialize once, write a same-directory staged file, and
  publish atomically. Escape every rendered dollar before serialization so
  Containerlab's own environment pass cannot expand the topology a second
  time. Remove the staged file on every exception.
- Retain the generated topology after deploy, including failed or interrupted
  deploys that may have created partial host state. Unlink it only after a
  successful destroy routed through that file.
- If a later preparer fails before Containerlab starts, remove a newly generated
  topology or atomically restore the retained topology that this preparation
  replaced.
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
derived topology. The writer deterministically maps a resolved source path to
one retained derived path, materializes once during preparation, doubles
dollar signs in every string key/value to preserve the parser's already
rendered values through Containerlab's substitution pass, preserves YAML key
order where possible, and owns only its recognizable generated and staged
paths. A redeploy atomically replaces that same path. Deploy postprocessing
retains it; successful destroy postprocessing removes it after Containerlab has
used the full node and management configuration. Feature-specific state,
leases, validation, and mutation logic remain with the mutator.

Preparation remembers the exact prior bytes at the target. If a later plugin's
preparation fails, `prepare_failed()` atomically restores those bytes, or removes
the target when this invocation created it. A completed call discards that
rollback state; failed and interrupted deploy calls still retain the generated
topology because Containerlab may have created host state.

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
