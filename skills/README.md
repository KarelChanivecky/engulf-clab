# Repository-owned skills

The canonical `develop-eclab-lab` Codex skill is maintained in this directory
and released as the independent `develop-eclab-lab` Python package. The wheel
embeds the complete skill, so installation does not require an eclab or Engulf
source checkout.

## Contents

- [Source and installed layouts](#source-and-installed-layouts)
- [What is bundled](#what-is-bundled)
- [Update workflow](#update-workflow)
- [Install from a checkout](#install-from-a-checkout)
- [Install from a wheel](#install-from-a-wheel)
- [Repository hooks](#repository-hooks)
- [Add or change a reference](#add-or-change-a-reference)
- [Validate and release](#validate-and-release)
- [Troubleshooting](#troubleshooting)

## Source and installed layouts

The repository tree is both the canonical skill definition and a Python build
project:

```text
skills/develop-eclab-lab/
├── SKILL.md
├── agents/openai.yaml
├── references/
├── src/develop_eclab_lab_skill/
├── LICENSE
└── pyproject.toml
```

`SKILL.md` contains the essential workflow. `agents/openai.yaml` contains the
skill-list presentation metadata. Detailed Engulf, executable-wrapper, eclab,
MCP, and plugin documentation lives under `references/` and is loaded only when
the task needs it. The Python package contains the installer; Hatch copies the
definition, metadata, and references into
`develop_eclab_lab_skill/bundle/` inside the wheel.

The default installed output is:

```text
$CODEX_HOME/skills/develop-eclab-lab/
├── SKILL.md
├── agents/openai.yaml
└── references/
```

When `CODEX_HOME` is unset, the installer uses
`~/.codex/skills/develop-eclab-lab`. Use `--skills-dir` when another agent host
expects the shared `.agents/skills` convention or a custom discovery root.

Treat that directory as generated. Make changes in the repository and reinstall
instead of editing an installed copy.

## What is bundled

`scripts/develop_eclab_lab_skill.py` defines the source-to-reference mapping.
The package contains snapshots of:

- the root eclab overview and repository development rules;
- the wrapper and privileged MCP service guides;
- every maintained plugin README and plugin-specific `AGENTS.md`;
- detailed packaged-container guides;
- the public Engulf API and runtime documentation; and
- the executable-wrapper API and lifecycle documentation.

`references/source-index.md` is the human-readable routing index. The updater
normalizes product-specific examples into generic lab terminology and rejects
any remaining forbidden vendor-specific text. This keeps the skill reusable
across base eclab and independently packaged editions.

Runtime help remains the authority for which plugins are installed in a user's
actual launcher. Bundled references describe contracts and troubleshooting
context; they do not prove that a feature is active in a particular base eclab,
edition, local CLI environment, or MCP service profile.

## Update workflow

Use the source updater whenever mirrored documentation changes:

```bash
ENGULF_DIR=../cliwrap ./scripts/update-develop-eclab-lab
```

`ENGULF_DIR` identifies the Engulf checkout that supplies the API/runtime
snapshots. Without it, the script uses the adjacent `../engulf` path and skips
unavailable Engulf sources unless `--require-engulf` is passed. For release and
CI validation, require the checkout explicitly:

```bash
ENGULF_DIR=../cliwrap ./scripts/update-develop-eclab-lab --check --require-engulf
```

The corresponding Make targets are:

```bash
make update-skill
make check-skill
```

After editing `SKILL.md`, also confirm that `agents/openai.yaml` still describes
the same behavior and that its default prompt names `$develop-eclab-lab`.

## Install from a checkout

The repository installer validates the canonical skill, installs a standalone
copy, and configures this checkout's Git hooks:

```bash
make install-skill
```

It refuses to replace a non-skill path and refuses to overwrite an unrelated
`core.hooksPath`. If no hook path is configured, it sets the repository-local
value to `.githooks`. A recognized older skill installation is moved to the
backup directory before the new tree is published atomically.

The checkout installer uses the following defaults:

| Setting | Default | Override |
| --- | --- | --- |
| Skills parent directory | `$CODEX_HOME/skills`, otherwise `~/.codex/skills` | `DEVELOP_ECLAB_LAB_SKILLS_DIR` or `--skills-dir` |
| Backup directory | `~/.local/state/develop-eclab-lab/backups` | `DEVELOP_ECLAB_LAB_BACKUP_DIR` |

## Install from a wheel

Build or install the independent package, then run its console command:

```bash
python3.14 -m pip install develop-eclab-lab
develop-eclab-lab-install
```

Useful installer options are:

```text
--skills-dir PATH   Override the parent skills directory
--backup-dir PATH   Override the backup directory
--check             Verify that the installed tree exactly matches the wheel
```

Environment variables establish defaults; explicit command options take
precedence. `--check` is read-only apart from a temporary comparison directory,
which is always removed. Installation copies only `SKILL.md`, Markdown/YAML
resources, and the `agents` and `references` trees. It does not retain a link to
the wheel or checkout.

To test a wheel without touching a real user installation, use temporary
directories:

```bash
python3.14 -m venv /tmp/develop-eclab-lab-test
/tmp/develop-eclab-lab-test/bin/python -m pip install dist/develop-eclab-lab/*.whl
DEVELOP_ECLAB_LAB_SKILLS_DIR=/tmp/eclab-skills \
  /tmp/develop-eclab-lab-test/bin/develop-eclab-lab-install
DEVELOP_ECLAB_LAB_SKILLS_DIR=/tmp/eclab-skills \
  /tmp/develop-eclab-lab-test/bin/develop-eclab-lab-install --check
```

## Repository hooks

`.githooks/pre-commit` validates the staged index, not merely the working tree.
When a mirrored local source is staged, its generated reference must also be
staged and byte-for-byte equal after normalization. Every staged file within
the skill is scanned for forbidden product-specific text.

`.githooks/commit-msg` evaluates paths that can change runtime behavior or
documentation. Such a commit must contain exactly one of:

```text
Skill-Impact: updated
Skill-Impact: none
```

`updated` means the skill or a bundled snapshot changed and requires at least
one staged path below `skills/develop-eclab-lab/`. `none` records an explicit
review decision. Tests, skill tooling, and hook-only changes do not
automatically claim that runtime guidance changed, but should still update the
skill when their semantics affect users.

## Add or change a reference

1. Put authoritative user documentation in a package `README.md` and
   contributor invariants in its nearest `AGENTS.md`.
2. Add the source and destination filename to `LOCAL_SOURCES` or
   `ENGULF_SOURCES` in `scripts/develop_eclab_lab_skill.py`.
3. If genericization is required, add the smallest explicit transformation to
   `NORMALIZATIONS`. Never use normalization to hide a behavior difference.
4. Add the destination and source description to
   `references/source-index.md`.
5. Link the reference directly from `SKILL.md` when an agent must know when to
   load it. Avoid reference-to-reference navigation chains.
6. Run the updater, inspect the generated diff, and search the entire skill for
   stale names, private paths, credentials, and product-specific assumptions.

Do not hand-maintain copied reference prose. Fix the authoritative source and
regenerate it. Keep detailed schemas and examples in references rather than
expanding the always-loaded `SKILL.md`.

## Validate and release

Run these checks after a skill change:

```bash
ENGULF_DIR=../cliwrap make check-skill
SKILL_CREATOR_DIR=/path/to/skill-creator
.venv/bin/python "$SKILL_CREATOR_DIR/scripts/quick_validate.py" \
  skills/develop-eclab-lab
.venv/bin/python -m build --no-isolation skills/develop-eclab-lab
.venv/bin/python -m twine check skills/develop-eclab-lab/dist/*
git diff --check
```

The `quick_validate.py` location is installation-specific; use the validator
from the active skill-creator installation. A clean temporary wheel install and
`develop-eclab-lab-install --check` verify that package data and installer
behavior match the source tree.

Before publishing, increment the package version when the distributed skill
changes. Review `SKILL.md`, `agents/openai.yaml`, the source index, wheel file
list, and normalized references together. The root `make build` command includes
the skill distribution in the monorepo release artifact set.

## Troubleshooting

- **A mirrored source is stale:** run the updater, then stage the source and
  generated reference together.
- **The Engulf checkout cannot be found:** set `ENGULF_DIR` explicitly; use
  `--require-engulf` when skipping it would make validation incomplete.
- **The installer refuses a destination:** inspect it manually. The installer
  replaces only a directory containing a recognized `develop-eclab-lab`
  definition.
- **The installed check differs:** reinstall from the same wheel or checkout;
  do not patch the installed output.
- **A hook path is already configured:** preserve the existing hook manager and
  invoke the repository scripts from that manager instead of overwriting it.
- **Forbidden text appears in a source guide:** make the canonical guide generic
  when its behavior is generic; otherwise add a narrow, reviewed normalization
  for the bundled skill snapshot.
- **Runtime help and a reference disagree:** trust the help for installed
  availability, then determine whether the reference is stale or the installed
  package version differs.
