# Plugin Instructions

This collector runs after topology mutators and retains one stable derived YAML
file until Containerlab successfully destroys the lab.

- Keep plugin ID `engulf_clab.lab_writer`, priority `-100`, parser dependency,
  and topology-context read stable.
- Activate only for deploy. During analysis, remove all source topology option
  tokens and contribute exactly one generated `-t` pair before the separator.
- Place the target beside the source topology at the deterministic
  `.engulf-clab-lab-<source-id>.clab.yml` path so labels retain a usable destroy
  topology and relative paths retain source semantics.
- In preparation, materialize once, write a same-directory staged file, and
  publish atomically. Escape every rendered dollar before serialization so
  Containerlab's own environment pass cannot expand the topology a second
  time. Remove the staged file on every exception.
- Retain the generated topology after deploy, including failed or interrupted
  deploys that may have created partial host state. Unlink it only after a
  successful destroy routed through that file.
- Never write, rename, or delete the selected source topology. Do not own feature
  mutation logic, state, leases, or runtime help.
- Keep `CONTRIBUTING.md` argv/integration detail and `USAGE.md` user-visible
  file/cleanup behavior synchronized with parser contracts.
- Run writer plus parser and direct mutator tests. Use temporary files; never run
  Containerlab. Keep schema registration separate from temporary-file work.
