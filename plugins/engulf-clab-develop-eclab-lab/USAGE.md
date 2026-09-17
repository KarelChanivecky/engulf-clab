# Runtime-generated lab development skill

This eclab plugin installs a Codex-compatible lab skill generated from the
active plugin set and the exact selected Containerlab and vrnetlab sources:

```bash
python -m pip install engulf-clab-develop-eclab-lab
eclab install-develop-eclab-lab-skill ~/.codex
```

Install the skill distribution into the same environment as the wrapper, since
Engulf discovers plugins from the wrapper's environment. The beta release
requires the Engulf 1.0 plugin APIs used for packaging-declared dependency
ordering.

Pass the configuration root that contains `skills/`, not the skills directory.
Base eclab installs `~/.codex/skills/develop-eclab-lab`. The command is also an
idempotent refresh.

The installed `SKILL.md` combines durable cross-plugin lab guidance with the
catalog current at generation time. The skill keeps fingerprinted runtime
bundles under `references/runtimes/`; `references/current.json` identifies the
active one. It uses its embedded catalog first, uses `catalog.json` for
structured queries, then loads only task-relevant
`plugins/<plugin-id>/schema.yaml` files and detailed references, reserving the
full composed schema for final topology validation.

The configuration root must already exist and must not be a symlink. The
installer also refuses a symlinked `skills/` directory, a symlinked target, and
an unrelated target. Recognized replacements are moved beneath
`.develop-eclab-lab-backups/<timestamp>` before the staged update is published
atomically. Only the latest skill backup is retained; older backups are
removed, while older runtime bundles remain available for existing conversations.

Explicitly installed roots are tracked for best-effort refresh after later
eclab calls. An incomplete recognized target is repaired from the cached bundle.
Deleting the whole generated target or removing its ownership marker untracks
that root from automatic refresh. Explicit installation failures return nonzero, while an
automatic refresh failure cannot change the wrapped command's result.

This collector runs only under the base `eclab` executable. A superset edition
registers and requests its own schema pipeline, consumes its `CompiledSchemaBundle`,
and owns its separate skill renderer, command, and installation target, so both
edition-specific skills can exist side by side without being regenerated
together. This package does not expose a generic template-composition API.

If the obsolete `engulf-clab-develop-lab-skill` distribution is installed,
remove it before upgrading to avoid duplicate discovery of the same plugin ID.
