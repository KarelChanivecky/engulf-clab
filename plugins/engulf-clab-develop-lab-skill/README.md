# Runtime-generated lab development skill

This Engulf plugin installs a Codex-compatible lab development skill containing
the schema and documentation contributed by the exact active plugin set.

Install the stable eclab skill distribution in the same environment as the
wrapper:

```bash
python -m pip install engulf-clab-develop-eclab-lab
```

The older `engulf-clab-develop-lab-skill` distribution name was a short-lived
development artifact. Remove it before upgrading if it is present, so Engulf
does not discover the same plugin ID twice.

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

The catalog also contains a `containerlab.node_kinds` provider generated from
the resolved Containerlab and vrnetlab repositories. Its compact index routes
each exact `kind:` to one small YAML record and only the upstream documents
available for that kind; custom source repositories therefore produce custom
skill guidance.

The installed `SKILL.md` combines durable cross-plugin lab guidance with the
current catalog appended at generation time. Catalog paths are rewritten to be
relative to the skill directory, so the agent can route directly from its
loaded instructions to the current fingerprint's small provider YAML files.

Only recognized generated installations are replaced. Symlinks and unrelated
directories are refused. Explicitly installed configuration roots are tracked
for best-effort refresh after later launcher calls. No automatic schema build is
requested when that tracking list is empty. A complete target reports its
installed fingerprint to the generator, so an unchanged cached bundle requires
neither compilation nor a rewrite. An incomplete recognized target is repaired
from the cached bundle; deleting the whole generated target removes that root
from automatic refresh. Help-only invocations do not inspect tracking state or
request an automatic refresh; neither does the latency-sensitive internal shell
completion protocol.
An existing symlink or target without the ownership marker is left untouched and
removed from automatic tracking.
