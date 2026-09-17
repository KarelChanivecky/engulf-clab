# Plugin instructions

- Read `CONTRIBUTING.md`, `USAGE.md`, source, schema, help, and tests together.
- Own persistence and deploy/redeploy observation in this plugin.
- Expose records only through `engulf-clab-lab-registry-api`.
- Publish records, never a state handle; do every read and write in own callbacks.
- Keep transactions short and never change a goal result because tracking failed.
- Bump the stored revision only when the recorded labs change; an idempotent
  retry must leave it, and any plan fenced to it, valid.
- Fence the commit per key against the load-time snapshot so a concurrent
  writer's newer entry is never replaced by a stale flush.
- Publish and acknowledge a `RegistryCommit` in `after_goal`; destructive
  consumers order themselves after it and refuse to delete without it.
- Retain records on destroy and avoid recursive filesystem discovery.
- Keep Docker observation read-only and mock it in tests.
- Declare ordering in packaging and run registry, API, consumer, and skill tests.
