# Skill contribution API

Install `engulf-clab-skill-api` in the same Python environment as the wrapper
plugins that use it. A contributing plugin declares the collector as a package
dependency and calls `record_skill()` from its invocation callbacks:

```python
from pathlib import Path

from engulf_clab_skill_api import record_skill

record_skill(api, Path(__file__).resolve().parent / "skills" / "example")
```

Each path must be absolute and point to one complete skill directory containing
`SKILL.md`. The directory name becomes the installed skill name. Package the
directory with the contributing distribution. The API records paths only; it
does not read, copy, or embed skill contents.

## Static packaged skills

For a static skill, use `contribute_static_skill()` from the provider's
`after_goal()` callback. The helper copies the packaged directory into that
provider's user-scoped state at `skill-export/<name>/`, merges any supplied
relative extra files, and registers the resulting absolute path when an
explicit install is requested or that skill name is already tracked:

```python
from pathlib import Path

from engulf_clab_skill_api import contribute_static_skill

contribute_static_skill(
    api,
    invocation,
    name="example-skill",
    packaged_dir=Path(__file__).resolve().parent / "skill",
    extra_files={"agents/openai.yaml": b"interface:\n  display_name: Example\n"},
)
```

The helper skips help, internal protocol, and ordinary untracked invocations.
It fingerprints the packaged tree and extra files, reuses an unchanged export,
and stages changed exports before replacing the previous directory. Its return
value is the absolute exported path, or `None` when the invocation is gated
out. Extra file names must be relative POSIX paths that contain no `..`.

The calling plugin declares the shared contexts in its own contract:

```python
from engulf_clab_skill_api import (
    SKILL_CONTRIBUTION_CONTEXTS,
    SKILL_PATHS_CONTEXT,
)

context_reads = SKILL_CONTRIBUTION_CONTEXTS
context_writes = frozenset({SKILL_PATHS_CONTEXT})
```

`SKILL_CONTRIBUTION_CONTEXTS` includes both the contribution registry and the
collector's tracked target paths. The API stores only paths in shared context;
the copied skill contents remain in the contributing plugin's state until the
collector installs them.

## Invocation-scoped generated skills

For generated content that is only needed while the collector copies or refreshes
it, call `record_temporary_skill()` instead of `record_skill()`. The provider
declares `SKILL_TEMPORARY_PATHS_CONTEXT` in both `context_reads` and
`context_writes`, alongside the normal skill path contexts. The collector removes
the marked source tree and its empty per-invocation parent after its install or
refresh attempt, including early returns and handled failures. Providers should
still clean up if registration itself fails; the eclab generated provider also
cleans its process-owned state at exit and reaps abandoned process state on the
next generation.

Declare the collector ordering edge in the provider distribution so paths are
available before its installation callback:

```toml
[project.entry-points."engulf.plugins.v1.dependency.example_skill_provider"]
"engulf_clab.skill_collector" = "preprocess=before; postprocess=after"
```

The shared collector's `install-skills CONFIG_ROOT` command installs all paths
contributed by active plugins to `CONFIG_ROOT/skills/`. The collector tracks
explicitly installed roots and refreshes tracked skills when their source
contents change. A skill path may also be published after compilation when its
contents are generated at runtime. The collector rejects duplicate directory
names and refuses to overwrite symlinked or unrecognized targets.
