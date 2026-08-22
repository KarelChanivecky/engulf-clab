# Runtime-generated lab development skill

This Engulf plugin installs a Codex-compatible lab development skill containing
the schema and documentation contributed by the exact active plugin set.

Run the command advertised by the selected launcher, passing the configuration
root that owns `skills/`. For base eclab:

```bash
eclab install-develop-eclab-lab-skill ~/.codex
```

The destination is `~/.codex/skills/develop-eclab-lab`. The command also acts as
an idempotent refresh. Generated runtime bundles are fingerprinted, previous
bundles are retained, and `references/current.json` selects the current one.
The generated skill uses its embedded catalog first, uses `catalog.json` for
structured queries, then loads only task-relevant
`plugins/<plugin-id>/schema.yaml` files and detailed references. It treats the
composed schema as final topology validation rather than as its discovery
interface.

The installed `SKILL.md` combines durable cross-plugin lab guidance with the
current catalog appended at generation time. Catalog paths are rewritten to be
relative to the skill directory, so the agent can route directly from its
loaded instructions to the current fingerprint's small provider YAML files.

Only recognized generated installations are replaced. Symlinks and unrelated
directories are refused. Explicitly installed configuration roots are tracked
for best-effort refresh after later launcher calls; deleting a generated target
removes that root from automatic refresh.
