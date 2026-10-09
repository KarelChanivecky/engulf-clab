from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Self

import pytest
from engulf_api import GoalResult, Invocation
from engulf_clab_skill_api import SKILL_PATHS_CONTEXT, SKILL_TEMPORARY_PATHS_CONTEXT

from engulf_clab_skill_collector.plugin import (
    INSTALL_REQUEST_CONTEXT,
    MARKER_NAME,
    PLUGIN_ID,
    InstallRequest,
    SkillCollectorPlugin,
    _validate_sources,
)


class _API:
    logger = logging.getLogger("skill-collector-test")


def _source(root: Path, name: str, text: str = "# Test skill\n") -> Path:
    path = root / name
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(text, encoding="utf-8")
    return path


def test_install_paths_copies_multiple_skills_and_records_owner(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    first = _source(source_root, "first-skill", "# First\n")
    second = _source(source_root, "second-skill", "# Second\n")
    config_root = tmp_path / "codex"
    config_root.mkdir()

    installed = SkillCollectorPlugin()._install_paths(
        _API(), config_root, (first, second)  # type: ignore[arg-type]
    )

    assert installed == ("first-skill", "second-skill")
    target = config_root / "skills" / "first-skill"
    assert (target / "SKILL.md").read_text() == "# First\n"
    marker = json.loads((target / MARKER_NAME).read_text())
    assert marker["owner"] == PLUGIN_ID
    assert marker["skill_name"] == "first-skill"
    assert len(marker["fingerprint"]) == 64


def test_changed_source_replaces_only_recognized_target_and_keeps_latest_backup(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    source = _source(source_root, "sample-skill", "# Version one\n")
    config_root = tmp_path / "codex"
    config_root.mkdir()
    collector = SkillCollectorPlugin()

    collector._install_paths(_API(), config_root, (source,))  # type: ignore[arg-type]
    (source / "SKILL.md").write_text("# Version two\n", encoding="utf-8")
    collector._install_paths(_API(), config_root, (source,))  # type: ignore[arg-type]

    target = config_root / "skills" / "sample-skill"
    assert (target / "SKILL.md").read_text() == "# Version two\n"
    backups = config_root / "skills" / ".sample-skill-backups"
    backup_dirs = [path for path in backups.iterdir() if path.is_dir()]
    assert len(backup_dirs) == 1
    assert (backup_dirs[0] / "SKILL.md").read_text() == "# Version one\n"


def test_unchanged_target_prunes_interrupted_install_backups(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    source = _source(source_root, "sample-skill", "# Current\n")
    config_root = tmp_path / "codex"
    config_root.mkdir()
    collector = SkillCollectorPlugin()

    collector._install_paths(_API(), config_root, (source,))  # type: ignore[arg-type]
    backups = config_root / "skills" / ".sample-skill-backups"
    backups.mkdir()
    for suffix in ("100", "200", "300"):
        backup = _source(backups, suffix, f"# Backup {suffix}\n")
        (backup / MARKER_NAME).write_text(
            json.dumps(
                {
                    "owner": PLUGIN_ID,
                    "skill_name": "sample-skill",
                    "fingerprint": "a" * 64,
                }
            ),
            encoding="utf-8",
        )

    collector._install_paths(_API(), config_root, (source,))  # type: ignore[arg-type]

    retained = list(backups.iterdir())
    assert [path.name for path in retained] == ["300"]


def test_duplicate_names_are_rejected_before_any_install(tmp_path: Path) -> None:
    first_root = tmp_path / "a"
    second_root = tmp_path / "b"
    first_root.mkdir()
    second_root.mkdir()
    first = _source(first_root, "same-name")
    second = _source(second_root, "same-name")
    config_root = tmp_path / "codex"
    config_root.mkdir()

    with pytest.raises(ValueError, match="duplicate skill directory name"):
        SkillCollectorPlugin()._install_paths(
            _API(), config_root, (first, second)  # type: ignore[arg-type]
        )

    assert not (config_root / "skills").exists()


def test_unrecognized_target_is_never_replaced(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    source = _source(source_root, "sample-skill")
    config_root = tmp_path / "codex"
    target = config_root / "skills" / "sample-skill"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("# User content\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unrecognized path"):
        SkillCollectorPlugin()._install_paths(
            _API(), config_root, (source,)  # type: ignore[arg-type]
        )

    assert (target / "SKILL.md").read_text() == "# User content\n"


def test_source_requires_skill_entrypoint_and_safe_name(tmp_path: Path) -> None:
    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()
    with pytest.raises(ValueError, match="no regular SKILL.md"):
        _validate_sources((incomplete,))

    unsafe = tmp_path / "UPPERCASE"
    unsafe.mkdir()
    (unsafe / "SKILL.md").write_text("# Unsafe\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid skill directory name"):
        _validate_sources((unsafe,))


def test_source_symlink_is_rejected(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    source = _source(source_root, "sample-skill")
    outside = tmp_path / "outside.txt"
    outside.write_text("not part of a skill", encoding="utf-8")
    (source / "external.txt").symlink_to(outside)

    with pytest.raises(ValueError, match="symbolic link"):
        _validate_sources((source,))


def test_after_goal_cleans_temporary_source_even_when_tracking_is_skipped(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "generated-skills" / "invocation-1"
    source = _source(source_root, "develop-eclab-lab")

    class _ContextAPI:
        logger = _API.logger

        def get_context(self, context_id: str, default: object | None = None) -> object | None:
            if context_id == SKILL_TEMPORARY_PATHS_CONTEXT:
                return (source,)
            return default

    result = SkillCollectorPlugin().after_goal(
        Invocation(("help",), tmp_path, {}),
        GoalResult.completed(),
        _ContextAPI(),  # type: ignore[arg-type]
    )

    assert result.exit_code == 0
    assert not source.exists()
    assert not source_root.exists()


def test_after_goal_installs_then_cleans_temporary_source(tmp_path: Path) -> None:
    source_root = tmp_path / "generated-skills" / "invocation-install"
    source = _source(source_root, "develop-eclab-lab", "# Generated\n")
    config_root = tmp_path / "codex"
    config_root.mkdir()

    class _State:
        def exists(self, name: str) -> bool:
            del name
            return False

        def transaction(self) -> _State:
            return self

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def write_text(self, name: str, text: str) -> None:
            del name, text

    class _ContextAPI:
        logger = _API.logger

        def __init__(self) -> None:
            self.values = {
                SKILL_PATHS_CONTEXT: (source,),
                SKILL_TEMPORARY_PATHS_CONTEXT: (source,),
                INSTALL_REQUEST_CONTEXT: InstallRequest(config_root),
            }
            self._state = _State()

        def get_context(self, context_id: str, default: object | None = None) -> object | None:
            return self.values.get(context_id, default)

        def state(self, scope: object) -> _State:
            del scope
            return self._state

        def lease(self, name: str) -> _ContextAPI:
            del name
            return self

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            del args

    result = SkillCollectorPlugin().after_goal(
        Invocation(("install-skills", str(config_root)), tmp_path, {}),
        GoalResult.completed(),
        _ContextAPI(),  # type: ignore[arg-type]
    )

    assert result.exit_code == 0
    assert (config_root / "skills" / "develop-eclab-lab" / "SKILL.md").read_text() == "# Generated\n"
    assert not source.exists()
    assert not source_root.exists()


def test_after_goal_cleans_temporary_source_when_collection_raises(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "generated-skills" / "invocation-2"
    source = _source(source_root, "develop-eclab-lab")

    class _ContextAPI:
        logger = _API.logger

        def get_context(self, context_id: str, default: object | None = None) -> object | None:
            if context_id == SKILL_TEMPORARY_PATHS_CONTEXT:
                return (source,)
            raise RuntimeError("simulated collector failure")

    with pytest.raises(RuntimeError, match="simulated collector failure"):
        SkillCollectorPlugin().after_goal(
            Invocation(("deploy",), tmp_path, {}),
            GoalResult.completed(),
            _ContextAPI(),  # type: ignore[arg-type]
        )

    assert not source.exists()
    assert not source_root.exists()
