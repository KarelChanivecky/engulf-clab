# Install contributed skills

Install `engulf-clab-skill-collector` and the plugin packages whose skills you
want to install in the same environment as the eclab wrapper:

```bash
python -m pip install engulf-clab-skill-collector engulf-clab-develop-eclab-lab
eclab install-skills ~/.codex
```

The exact syntax is `eclab install-skills CONFIG_ROOT`. `CONFIG_ROOT` is an
existing directory containing or ready to contain `skills/`; do not pass the
`skills/` directory itself. The collector copies every active contributed skill
directory to `CONFIG_ROOT/skills/<directory-name>/`. No environment variables
or edition-prefixed settings are used. Another launcher can use the same command
when it installs the collector and skill-contributing plugins.

Each provider package contributes an absolute path to a complete skill folder
that contains `SKILL.md`. The folder name is the installed skill name, so active
providers must use distinct names. Installation copies the directory; updates to
the provider package do not modify an installed skill until a refresh occurs.

## Lifecycle and state

An explicit `install-skills` call installs all current contributions and tracks
the selected configuration root and installed names in the collector's
user-scoped Engulf state. Later invocations compare tracked source directories
with installed content and refresh changed skills. New skill names are installed
on the next explicit command. A missing target or target without a recognized
owner marker is removed from tracking. Automatic refresh is best effort; an
explicit installation error returns nonzero.

The collector stages each copy beside its target and renames it into place. It
keeps the most recent recognized backup under `skills/.<name>-backups/`. It
refuses symlinked configuration roots, skills directories, sources, files,
targets, and backup directories. It also refuses to replace an existing target
without a collector ownership marker, except for the recognized prior generated
`develop-eclab-lab` target, which can be upgraded by the new command.

Generated providers can mark their source paths as invocation-scoped. The
collector removes those source trees after its copy or refresh attempt, including
when no tracked target uses them. Installed targets keep only the current tree
and the most recent recognized backup.

Skill contents are trusted package data and are installed as files; the
collector does not interpret instructions in `SKILL.md`. Only install plugins
from sources you trust. Installed skills execute as prompt instructions in the
coding agent that loads them.

## Troubleshooting

- Use the configuration root, such as `~/.codex`, rather than `~/.codex/skills`.
- Check `eclab --help` for `install-skills`; absence means the collector is not
  active in that executable's environment.
- Resolve duplicate names by renaming one provider's skill directory.
- Remove or move an unrelated target yourself; the collector will not replace
  a target whose ownership marker it does not recognize.
- Run `install-skills` again after installing a new contributor package.
- The former `install-develop-eclab-lab-skill CONFIG_ROOT` command remains
  accepted as a compatibility alias for upgrading an existing generated lab
  skill.
