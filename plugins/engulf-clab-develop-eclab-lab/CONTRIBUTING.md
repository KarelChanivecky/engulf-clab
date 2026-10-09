# Generated lab skill contributor guidance

This package provides the eclab-specific content and renderer for
`develop-eclab-lab`. `engulf-clab-skill-api` owns the path-only shared context;
`engulf-clab-skill-collector` owns installation and refresh.

- Record the schema declaration during `before_goal()` and request compilation
  only for explicit installation or a tracked generated skill.
- The compiler runs after schema contributors. Its bundle is read from the
  existing compiled context, rendered into a unique per-invocation directory
  under this plugin's user state, and contributed with
  `record_temporary_skill(api, path)`.
- The collector removes temporary generated sources after every collection
  attempt. Keep process-exit cleanup for interruption and reap process roots
  left by exited or stale processes on the next generation. Clean the source if
  recording its path fails.
- Keep the path contribution small. Do not publish catalog text, schema bytes,
  references, or callbacks in the skill context.
- The generated target name and eclab pipeline are stable. Other editions own
  their own runtime-specific providers and may install separate skills through
  the shared collector.
- Keep package dependency ordering in `pyproject.toml`: this provider precedes
  the schema compiler in `before_goal`, consumes compiler output before its
  postprocessing, reads tracked names from the collector first, and publishes
  its path before the collector installs it.
- Do not configure logging or print operational messages directly. Report
  diagnostics through callback-bound `api.logger`.

## Validation

```bash
.venv/bin/python -m compileall -q plugins/engulf-clab-develop-eclab-lab/src
.venv/bin/python -m pytest -q plugins/engulf-clab-develop-eclab-lab/tests
make check-skill
```
