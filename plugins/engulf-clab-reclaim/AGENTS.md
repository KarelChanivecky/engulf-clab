# Plugin instructions

- Read `CONTRIBUTING.md`, `USAGE.md`, source, schema, help, and tests together.
- Keep planning read-only; record observations and let the registry owner commit
  them, and **delete only after the owner's committed confirmation**.
- Never flush a stale record over a newer one: fence against the registry
  revision and abort when a selected lab's committed record moved.
- Treat a Docker object that is already gone as success, so a retry after a
  crash mid-deletion is idempotent and never over-deletes.
- Preserve lab directories and registry history.
- Delete only selected lab containers, anonymous volumes, and planned image IDs.
- Preserve cross-lab shared images unless `--all` selects every known lab.
- Reject plain `--all` if any lab has containers; `--all --stopped` selects only
  labs with stopped containers and preserves images owned outside that subset.
- Never force Docker image removal or add broad prune behavior.
- Use callback logging, keep the reclamation lease around planning and mutation,
  and require no MCP.
- Measure Docker image, container, and local-volume storage before and after
  deletion, and report the nonnegative reduction in IEC units.
- Declare ordering in packaging and run package, consumer, and skill tests.
