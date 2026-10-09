# Skill API contributor notes

- This package owns only path registration and the shared invocation context.
  Installation, target ownership, persistence, and refresh belong to the
  collector plugin.
- Contributions may be recorded during `before_goal()` or `after_goal()`.
  This lets ordinary packaged skills register before execution and generated
  skills register after their compiler has produced them.
- Static packaged providers should call `contribute_static_skill()` from
  `after_goal()`. It materializes into that provider's user state, fingerprints
  wheel inputs, and records only the final absolute path in shared context.
- Providers using the static helper declare `SKILL_CONTRIBUTION_CONTEXTS` in
  `context_reads` and `SKILL_PATHS_CONTEXT` in `context_writes`.
- Generated sources that should not persist after collection use
  `record_temporary_skill()`. Those providers also declare
  `SKILL_TEMPORARY_PATHS_CONTEXT` in both `context_reads` and `context_writes`;
  the collector removes each registered source after installation or refresh.
- Do not snapshot directory contents in the API. The collector fingerprints
  source trees when deciding whether an installed target needs refresh.
- Keep the registry immutable and deduplicate repeated declarations of the
  same normalized absolute path.
- Tracked target paths are a separate small context for generated providers;
  never place target file contents or fingerprints derived from entire skill
  trees there.

## Validation

```bash
.venv/bin/python -m pytest -q plugins/engulf-clab-skill-api/tests
```
