# Plugin instructions

- Read `CONTRIBUTING.md`, `USAGE.md`, source, schema, help, and tests together.
- Keep planning read-only and persist registry observations before deletion.
- Preserve lab directories and registry history.
- Delete only selected lab containers, anonymous volumes, and planned image IDs.
- Preserve cross-lab shared images unless `--all` selects every known lab.
- Reject plain `--all` if any lab has containers; `--all --stopped` selects only
  labs with stopped containers and preserves images owned outside that subset.
- Never force Docker image removal or add broad prune behavior.
- Use callback logging, keep the sleep lease around planning and mutation, and
  require no MCP.
- Declare ordering in packaging and run package, consumer, and skill tests.
