from __future__ import annotations

import json
from pathlib import Path

import pytest
from engulf_api import Invocation, StateScope

from engulf_clab_skill_api import (
    INSTALL_COMMAND,
    SKILL_CONTRIBUTION_CONTEXTS,
    SKILL_PATHS_CONTEXT,
    SKILL_TRACKED_TARGETS_CONTEXT,
    contribute_static_skill,
    explicit_install,
    skip_contribution,
    tracked_target_exists,
)
from engulf_clab_skill_api.context import SKILL_CONTEXTS


class _State:
    def __init__(self, directory: Path) -> None:
        self.directory = directory


class _API:
    def __init__(self, state_directory: Path) -> None:
        self.values: dict[str, object] = {}
        self._state = _State(state_directory)

    def get_context(self, context_id: str, default: object | None = None) -> object | None:
        return self.values.get(context_id, default)

    def set_context(self, context_id: str, value: object, *, allow_unused: bool = False) -> None:
        del allow_unused
        self.values[context_id] = value

    def state(self, scope: StateScope) -> _State:
        assert scope is StateScope.USER
        return self._state


def _packaged_skill(root: Path, name: str = "packaged") -> Path:
    source = root / name
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Packaged skill\n", encoding="utf-8")
    (source / "references").mkdir()
    (source / "references" / "guide.md").write_text("Guide\n", encoding="utf-8")
    return source


def _invocation(
    arguments: tuple[str, ...],
    *,
    environment: dict[str, str] | None = None,
) -> Invocation:
    return Invocation(arguments, Path.cwd(), environment or {})


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ((INSTALL_COMMAND,), True),
        ((INSTALL_COMMAND, "/tmp/codex"), True),
        ((INSTALL_COMMAND, "--help"), False),
        ((INSTALL_COMMAND, "-h"), False),
        (("help", INSTALL_COMMAND), False),
        (("deploy",), False),
        ((), False),
    ],
)
def test_explicit_install_truth_table(arguments: tuple[str, ...], expected: bool) -> None:
    assert explicit_install(arguments) is expected


def test_contribution_context_constant_combines_path_and_tracking_contexts() -> None:
    assert SKILL_CONTRIBUTION_CONTEXTS == SKILL_CONTEXTS
    assert SKILL_PATHS_CONTEXT in SKILL_CONTRIBUTION_CONTEXTS
    assert SKILL_TRACKED_TARGETS_CONTEXT in SKILL_CONTRIBUTION_CONTEXTS


@pytest.mark.parametrize(
    ("arguments", "environment"),
    [
        ((), {}),
        (("--help",), {}),
        (("help",), {}),
        (("deploy",), {"ENGULF_INTERNAL_PROTOCOL": "1"}),
        (("deploy", "-h"), {}),
    ],
)
def test_skip_contribution_cases(
    arguments: tuple[str, ...],
    environment: dict[str, str],
) -> None:
    assert skip_contribution(arguments, environment)


def test_explicit_install_exports_files_and_records_one_absolute_path(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    source = _packaged_skill(tmp_path / "package")
    api = _API(state)

    exported = contribute_static_skill(
        api,  # type: ignore[arg-type]
        _invocation((INSTALL_COMMAND, str(tmp_path / "codex"))),
        name="example-skill",
        packaged_dir=source,
        extra_files={"agents/openai.yaml": b"interface:\n  display_name: Example\n"},
    )

    assert exported == state / "skill-export" / "example-skill"
    assert exported is not None and exported.is_absolute()
    assert exported.name == "example-skill"
    assert exported.resolve(strict=True) == exported
    assert api.values[SKILL_PATHS_CONTEXT] == (exported,)
    assert (exported / "SKILL.md").read_bytes() == b"# Packaged skill\n"
    assert (exported / "references" / "guide.md").read_bytes() == b"Guide\n"
    assert (exported / "agents" / "openai.yaml").read_bytes() == (
        b"interface:\n  display_name: Example\n"
    )


def test_explicit_install_contributes_during_internal_protocol(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    source = _packaged_skill(tmp_path / "package")
    api = _API(state)

    exported = contribute_static_skill(
        api,  # type: ignore[arg-type]
        _invocation(
            (INSTALL_COMMAND,),
            environment={"ENGULF_INTERNAL_PROTOCOL": "1"},
        ),
        name="example-skill",
        packaged_dir=source,
    )

    assert exported is not None
    assert api.values[SKILL_PATHS_CONTEXT] == (exported,)


def test_idempotent_export_preserves_existing_files_and_fingerprint(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    source = _packaged_skill(tmp_path / "package")
    api = _API(state)
    invocation = _invocation((INSTALL_COMMAND,))

    exported = contribute_static_skill(
        api,  # type: ignore[arg-type]
        invocation,
        name="example-skill",
        packaged_dir=source,
        extra_files={"agents/openai.yaml": b"agent"},
    )
    assert exported is not None
    sentinel = exported / "manual-sentinel.txt"
    sentinel.write_text("kept on the idempotence fast path", encoding="utf-8")

    second = contribute_static_skill(
        api,  # type: ignore[arg-type]
        invocation,
        name="example-skill",
        packaged_dir=source,
        extra_files={"agents/openai.yaml": b"agent"},
    )

    assert second == exported
    assert sentinel.read_text(encoding="utf-8") == "kept on the idempotence fast path"
    metadata = json.loads(
        (state / "skill-export" / ".example-skill.fingerprint.json").read_text(
            encoding="utf-8"
        )
    )
    assert metadata["skill_name"] == "example-skill"
    assert len(metadata["fingerprint"]) == 64


def test_stale_export_is_rewritten_from_packaged_source(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    source = _packaged_skill(tmp_path / "package")
    api = _API(state)
    invocation = _invocation((INSTALL_COMMAND,))

    exported = contribute_static_skill(
        api,  # type: ignore[arg-type]
        invocation,
        name="example-skill",
        packaged_dir=source,
    )
    assert exported is not None
    (exported / "SKILL.md").write_text("# Stale\n", encoding="utf-8")
    (state / "skill-export" / ".example-skill.fingerprint.json").write_text(
        json.dumps({"skill_name": "example-skill", "fingerprint": "0" * 64}),
        encoding="utf-8",
    )

    rewritten = contribute_static_skill(
        api,  # type: ignore[arg-type]
        invocation,
        name="example-skill",
        packaged_dir=source,
    )

    assert rewritten == exported
    assert (rewritten / "SKILL.md").read_text(encoding="utf-8") == "# Packaged skill\n"


def test_untracked_normal_invocation_does_not_export(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    source = _packaged_skill(tmp_path / "package")
    api = _API(state)

    result = contribute_static_skill(
        api,  # type: ignore[arg-type]
        _invocation(("deploy",)),
        name="example-skill",
        packaged_dir=source,
    )

    assert result is None
    assert SKILL_PATHS_CONTEXT not in api.values
    assert not (state / "skill-export").exists()


def test_tracked_target_gates_automatic_export(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    source = _packaged_skill(tmp_path / "package")
    api = _API(state)
    api.values[SKILL_TRACKED_TARGETS_CONTEXT] = (
        tmp_path / "codex" / "skills" / "example-skill",
    )

    assert tracked_target_exists(api, "example-skill")  # type: ignore[arg-type]
    exported = contribute_static_skill(
        api,  # type: ignore[arg-type]
        _invocation(("deploy",)),
        name="example-skill",
        packaged_dir=source,
    )

    assert exported is not None
    assert api.values[SKILL_PATHS_CONTEXT] == (exported,)


def test_skip_flags_win_over_tracked_target(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    source = _packaged_skill(tmp_path / "package")
    api = _API(state)
    api.values[SKILL_TRACKED_TARGETS_CONTEXT] = (
        tmp_path / "codex" / "skills" / "example-skill",
    )

    for invocation in (
        _invocation(()),
        _invocation(("help", "deploy")),
        _invocation(("deploy", "--help")),
        _invocation(("deploy",), environment={"ENGULF_INTERNAL_PROTOCOL": "1"}),
    ):
        assert (
            contribute_static_skill(
                api,  # type: ignore[arg-type]
                invocation,
                name="example-skill",
                packaged_dir=source,
            )
            is None
        )
    assert SKILL_PATHS_CONTEXT not in api.values


def test_failure_from_unwritable_state_leaves_no_partial_export(tmp_path: Path) -> None:
    state_file = tmp_path / "state"
    state_file.write_text("not a directory", encoding="utf-8")
    source = _packaged_skill(tmp_path / "package")
    api = _API(state_file)

    with pytest.raises(OSError):
        contribute_static_skill(
            api,  # type: ignore[arg-type]
            _invocation((INSTALL_COMMAND,)),
            name="example-skill",
            packaged_dir=source,
        )

    assert not (state_file / "skill-export").exists()
    assert api.values == {}


def test_export_is_compatible_with_collector_validation(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    source = _packaged_skill(tmp_path / "package")
    api = _API(state)

    exported = contribute_static_skill(
        api,  # type: ignore[arg-type]
        _invocation((INSTALL_COMMAND,)),
        name="example-skill",
        packaged_dir=source,
        extra_files={"references/generated.md": b"generated"},
    )

    assert exported is not None
    assert exported.name == "example-skill"
    assert exported.resolve(strict=True) == exported
    assert (exported / "SKILL.md").is_file()
    assert not (exported / "SKILL.md").is_symlink()
    assert all(not path.is_symlink() for path in exported.rglob("*"))


@pytest.mark.parametrize("relative", ["/outside.txt", "../outside.txt", "nested/../../outside.txt"])
def test_extra_files_cannot_escape_the_skill_tree(tmp_path: Path, relative: str) -> None:
    state = tmp_path / "state"
    state.mkdir()
    source = _packaged_skill(tmp_path / "package")

    with pytest.raises(ValueError, match="must stay inside"):
        contribute_static_skill(
            _API(state),  # type: ignore[arg-type]
            _invocation((INSTALL_COMMAND,)),
            name="example-skill",
            packaged_dir=source,
            extra_files={relative: b"escape"},
        )

    assert not (state / "skill-export").exists()
