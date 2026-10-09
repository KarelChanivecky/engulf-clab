"""Invocation-scoped skill paths that the collector removes after copying."""

from __future__ import annotations

from pathlib import Path

from engulf_api import InvocationAPI

from .context import record_skill

SKILL_TEMPORARY_PATHS_CONTEXT = "engulf_clab.skills.temporary_paths"


def record_temporary_skill(api: InvocationAPI, path: Path) -> None:
    """Contribute a skill source that the collector should remove after use.

    The source directory must be unique to this invocation. Providers should
    use this for generated snapshots that are only needed until the collector
    has copied or attempted to refresh them.
    """
    if not isinstance(path, Path):
        raise TypeError("temporary skill path must be a pathlib.Path")
    if not path.is_absolute():
        raise ValueError("temporary skill path must be absolute")
    current = api.get_context(SKILL_TEMPORARY_PATHS_CONTEXT, ())
    if type(current) is not tuple or any(not isinstance(item, Path) for item in current):
        raise RuntimeError("invalid temporary skill path context")
    record_skill(api, path)
    if path not in current:
        api.set_context(
            SKILL_TEMPORARY_PATHS_CONTEXT,
            (*current, Path(path)),
            allow_unused=True,
        )


def temporary_skill_paths(api: InvocationAPI) -> tuple[Path, ...]:
    """Return paths that the collector must clean after its copy attempt."""
    value = api.get_context(SKILL_TEMPORARY_PATHS_CONTEXT, ())
    if type(value) is not tuple or any(
        not isinstance(item, Path) or not item.is_absolute() for item in value
    ):
        raise TypeError("invalid temporary skill path context")
    return value
