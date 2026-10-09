from pathlib import Path
from typing import Any

import pytest

from engulf_clab_skill_api import (
    SKILL_PATHS_CONTEXT,
    SKILL_TEMPORARY_PATHS_CONTEXT,
    SKILL_TRACKED_TARGETS_CONTEXT,
    publish_tracked_skill_targets,
    record_skill,
    record_temporary_skill,
    skill_paths,
    temporary_skill_paths,
    tracked_skill_names,
    tracked_skill_targets,
)


class _ContextAPI:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def get_context(self, context_id: str, default: object | None = None) -> object | None:
        return self.values.get(context_id, default)

    def set_context(
        self, context_id: str, value: object, *, allow_unused: bool = False
    ) -> None:
        del allow_unused
        self.values[context_id] = value


def test_record_skill_stores_paths_and_deduplicates() -> None:
    api = _ContextAPI()
    first = Path("/opt/example/skills/first")
    second = Path("/opt/example/skills/second")

    record_skill(api, first)  # type: ignore[arg-type]
    record_skill(api, first)  # type: ignore[arg-type]
    record_skill(api, second)  # type: ignore[arg-type]

    assert api.values[SKILL_PATHS_CONTEXT] == (first, second)
    assert skill_paths(api) == (first, second)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["/opt/skill", Path("relative/skill")])
def test_record_skill_rejects_non_path_and_relative_path(value: Any) -> None:
    with pytest.raises((TypeError, ValueError)):
        record_skill(_ContextAPI(), value)  # type: ignore[arg-type]


def test_tracked_skill_targets_use_a_separate_small_context() -> None:
    api = _ContextAPI()
    targets = (Path("/tmp/codex/skills/develop-eclab-lab"), Path("/tmp/codex/skills/example-helper"))

    publish_tracked_skill_targets(api, targets)  # type: ignore[arg-type]

    assert tracked_skill_targets(api) == targets  # type: ignore[arg-type]
    assert tracked_skill_names(api) == {"develop-eclab-lab", "example-helper"}  # type: ignore[arg-type]
    assert api.values[SKILL_TRACKED_TARGETS_CONTEXT] == targets


def test_skill_paths_rejects_malformed_context() -> None:
    api = _ContextAPI()
    api.values[SKILL_PATHS_CONTEXT] = [Path("/opt/skill")]

    with pytest.raises(TypeError, match="invalid skill path context"):
        skill_paths(api)  # type: ignore[arg-type]


def test_record_temporary_skill_registers_path_for_cleanup() -> None:
    api = _ContextAPI()
    path = Path("/tmp/generated/example-skill")

    record_temporary_skill(api, path)  # type: ignore[arg-type]
    record_temporary_skill(api, path)  # type: ignore[arg-type]

    assert api.values[SKILL_PATHS_CONTEXT] == (path,)
    assert api.values[SKILL_TEMPORARY_PATHS_CONTEXT] == (path,)
    assert temporary_skill_paths(api) == (path,)  # type: ignore[arg-type]


def test_temporary_skill_paths_rejects_malformed_context() -> None:
    api = _ContextAPI()
    api.values[SKILL_TEMPORARY_PATHS_CONTEXT] = [Path("/tmp/generated/example-skill")]

    with pytest.raises(TypeError, match="invalid temporary skill path context"):
        temporary_skill_paths(api)  # type: ignore[arg-type]
