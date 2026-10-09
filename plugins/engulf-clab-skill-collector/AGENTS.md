# Skill collector development notes

- The collector owns `install-skills CONFIG_ROOT`, target markers, root tracking,
  atomic installation, and best-effort refresh. Contributors only publish paths.
- The skill API context contains source paths, not file contents. Validate source
  trees and calculate content fingerprints in this package.
- Publish tracked target names during `before_goal()` so generated providers
  request compilation only when their installed skill is tracked. Read paths and
  install during `after_goal()` after path providers have run.
- Never replace symlinks or paths without a recognized collector marker. Accept
  only the legacy generated lab skill marker for its own target during upgrade.
- Keep state in this plugin's user-scoped `StateStore`, and use a short
  transaction for target-root updates.
- Always clean invocation-scoped source paths in `after_goal()` with `finally`,
  including skipped refreshes and installation failures. Cleanup must leave
  symlinks and non-canonical paths untouched.
- The schema declaration is support-only: it documents the command but adds no
  topology controls or task routes.
