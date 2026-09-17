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
- Log each resource successfully removed, including its Docker ID, in addition
  to the aggregate storage summary.
- Preserve cross-lab shared images unless `--all` selects every known lab.
- Reject plain `--all` if any lab has containers; `--all --stopped` selects only
  labs with stopped containers and preserves images owned outside that subset.
  Images shared only by labs in the selected subset are reclaimable.
- Never force Docker image removal or add broad prune behavior.
- Use callback logging, keep the reclamation lease around planning and mutation,
  and require no MCP.
- Measure Docker image, container, and local-volume storage before and after
  deletion, and report the nonnegative reclaimed amount in IEC units. For
  `destroy --reclaim`, the starting snapshot must precede native destroy so the
  report covers the complete operation.
- Declare ordering in packaging and run package, consumer, and skill tests.
- `destroy --reclaim` must plan before the native destroy call and execute only
  after a successful destroy. `destroy --all --reclaim` may plan deployed labs;
  plain `reclaim --all` retains its safety guard.
