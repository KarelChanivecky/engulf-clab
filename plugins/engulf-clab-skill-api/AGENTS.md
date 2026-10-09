# Skill API development notes

- Keep the shared context small: it contains an immutable tuple of absolute
  `Path` values, never file contents, callbacks, or state handles.
- `record_skill(api, path)` validates only the path's value type and absolute
  form; the collector validates installed skill contents. The static helper
  exports packaged trees to caller-owned user state before recording a path.
- Providers that generate one-invocation source trees use
  `record_temporary_skill()` and declare `SKILL_TEMPORARY_PATHS_CONTEXT` in
  their context reads and writes. The collector removes those paths after its
  copy or refresh attempt.
- Keep tracked target paths in a separate invocation context used only to let
  generated providers avoid unnecessary builds.
- Keep the static helper caller-agnostic: state comes from the supplied callback
  API, and shared contexts contain only paths.
- The API package is a contract library, not an Engulf plugin. It imports
  `engulf-api`, never the runtime.
