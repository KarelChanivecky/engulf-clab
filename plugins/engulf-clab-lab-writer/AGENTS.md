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
  publish atomically. Remove the staged file on every exception.
- In postprocessing, unlink only a path recognizable as this invocation's
  generated topology. Tolerate missing files and preserve the wrapped outcome.
- Never write, rename, or delete the selected source topology. Do not own feature
  mutation logic, state, leases, or runtime help.
- Keep README argv/file/cleanup behavior and parser contracts synchronized.
- Run writer plus parser and direct mutator tests. Use temporary files; never run
  Containerlab. Keep schema registration separate from temporary-file work.
