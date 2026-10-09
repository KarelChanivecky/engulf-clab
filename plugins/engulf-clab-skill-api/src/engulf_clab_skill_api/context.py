from __future__ import annotations

from pathlib import Path

from engulf_api import InvocationAPI

SKILL_PATHS_CONTEXT = "engulf_clab.skills.paths"
SKILL_TRACKED_TARGETS_CONTEXT = "engulf_clab.skills.tracked_targets"
SKILL_CONTEXTS = frozenset({SKILL_PATHS_CONTEXT, SKILL_TRACKED_TARGETS_CONTEXT})


def record_skill(api: InvocationAPI, path: Path) -> None:
    """Contribute the absolute path to one skill directory for this invocation."""
    if not isinstance(path, Path):
        raise TypeError("skill path must be a pathlib.Path")
    if not path.is_absolute():
        raise ValueError("skill path must be absolute")
    current = api.get_context(SKILL_PATHS_CONTEXT, ())
    if type(current) is not tuple or any(not isinstance(item, Path) for item in current):
        raise RuntimeError("invalid skill path registry")
    normalized = Path(path)
    if normalized not in current:
        api.set_context(SKILL_PATHS_CONTEXT, (*current, normalized), allow_unused=True)


def skill_paths(api: InvocationAPI) -> tuple[Path, ...]:
    """Return the immutable path contributions recorded in this invocation."""
    value = api.get_context(SKILL_PATHS_CONTEXT)
    if value is None:
        return ()
    if type(value) is not tuple or any(not isinstance(item, Path) for item in value):
        raise TypeError("invalid skill path context")
    return value


def publish_tracked_skill_targets(api: InvocationAPI, paths: tuple[Path, ...]) -> None:
    """Publish recognized installed skill paths for lazy generated providers."""
    if type(paths) is not tuple or any(
        not isinstance(item, Path) or not item.is_absolute() for item in paths
    ):
        raise TypeError("tracked skill targets must be absolute pathlib.Path values")
    current = tracked_skill_targets(api)
    api.set_context(
        SKILL_TRACKED_TARGETS_CONTEXT,
        tuple(sorted(set(current) | set(paths))),
        allow_unused=True,
    )


def tracked_skill_targets(api: InvocationAPI) -> tuple[Path, ...]:
    """Return recognized target paths published by the shared collector."""
    value = api.get_context(SKILL_TRACKED_TARGETS_CONTEXT, ())
    if type(value) is not tuple or any(
        not isinstance(item, Path) or not item.is_absolute() for item in value
    ):
        raise TypeError("invalid tracked skill targets context")
    return value


def tracked_skill_names(api: InvocationAPI) -> frozenset[str]:
    """Return directory names of recognized targets published by the collector."""
    return frozenset(path.name for path in tracked_skill_targets(api))
