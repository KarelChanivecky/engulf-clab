from __future__ import annotations

import importlib
import json
import os
import tomllib
from pathlib import Path
from typing import Any, Self

from engulf_api import ApplicationMetadata, GoalResult, Invocation
from engulf_clab_schema_api import SCHEMA_COMPILED_CONTEXT, CompiledSchemaBundle
from engulf_clab_skill_api import (
    SKILL_PATHS_CONTEXT,
    SKILL_TEMPORARY_PATHS_CONTEXT,
)

from engulf_clab_develop_lab_skill.plugin import (
    ECLAB_SKILL_NAME,
    PLUGIN_ID,
    DevelopLabSkillPlugin,
    _is_eclab_application,
    _prune_stale_generated_processes,
    _skip_automatic_refresh,
    _write_generated_skill,
    _write_static_skill,
    install_command,
)

ECLAB_APPLICATION = ApplicationMetadata(
    application_id="engulf-clab",
    display_name="ECLAB",
    vendor="Engulf",
    product="ECLAB",
    short_product_name="eclab",
    version="1.0",
)
EXTERNAL_APPLICATION = ApplicationMetadata(
    application_id="example-edition",
    display_name="Example Edition",
    vendor="Example",
    product="Example Containerlab",
    short_product_name="example-edition",
    version="1.0",
)


class _State:
    def __init__(self, root: Path) -> None:
        self.directory = root
        root.mkdir(parents=True, exist_ok=True)


class _API:
    def __init__(self, application: ApplicationMetadata, root: Path) -> None:
        self.application = application
        self.values: dict[str, object] = {}
        self._state = _State(root)

    def get_context(self, context_id: str, default: object | None = None) -> object | None:
        return self.values.get(context_id, default)

    def set_context(
        self, context_id: str, value: object, *, allow_unused: bool = False
    ) -> None:
        del allow_unused
        self.values[context_id] = value

    def lease(self, name: str) -> _API:
        del name
        return self

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def state(self, scope: object) -> _State:
        del scope
        return self._state

    class _Logger:
        def warning(self, *args: object) -> None:
            del args

        def error(self, *args: object) -> None:
            del args

    logger = _Logger()


def _bundle(fingerprint: str = "a" * 64) -> CompiledSchemaBundle:
    manifest = {
        "fingerprint": fingerprint,
        "pipeline": {"id": "eclab", "lineage": ["eclab"]},
        "plugins": [],
        "node_kinds": None,
    }
    return CompiledSchemaBundle(
        fingerprint=fingerprint,
        manifest=(json.dumps(manifest) + "\n").encode(),
        topology_schema=b"{}\n",
        catalog_json=b"{}\n",
        catalog_markdown=b"# Installed lab runtime catalog\n\n`plugins/example/schema.yaml`\n",
        references=(),
        pipeline_id="eclab",
    )


def test_eclab_names_and_concise_template() -> None:
    assert install_command() == "install-skills"
    assert ECLAB_SKILL_NAME == "develop-eclab-lab"

    import tempfile

    with tempfile.TemporaryDirectory() as temporary:
        target = Path(temporary) / "skill"
        _write_static_skill(target)
        definition = (target / "SKILL.md").read_text()
        agent = (target / "agents" / "openai.yaml").read_text()
        assert "name: develop-eclab-lab" in definition
        assert "eclab install-skills <CONFIG_ROOT>" in definition
        assert "compact\n   `schema.yaml`" in definition
        assert "full topology schema for validation" in definition
        assert "FortiGate" not in definition
        assert len(definition.split()) < 1000
        assert "$develop-eclab-lab" in agent
        assert "@@" not in definition + agent


def test_rendered_generated_skill_is_a_directory_for_path_contribution(tmp_path: Path) -> None:
    api = _API(ECLAB_APPLICATION, tmp_path / "provider-state")
    bundle = _bundle()

    source = _write_generated_skill(api, bundle)  # type: ignore[arg-type]
    second_source = _write_generated_skill(api, bundle)  # type: ignore[arg-type]

    assert source.is_absolute()
    assert source.name == ECLAB_SKILL_NAME
    assert len(source.parent.name) == 32
    assert source.parent.parent.name.startswith("process-")
    assert source.parent.parent.parent.name == "generated-skills"
    assert second_source != source
    assert source.is_dir()
    assert second_source.is_dir()
    assert (source / "SKILL.md").is_file()
    assert (source / "references" / "current.json").is_file()
    definition = (source / "SKILL.md").read_text()
    assert f"references/runtimes/{bundle.fingerprint}/plugins/example/schema.yaml" in definition


def test_stale_process_source_directories_are_reaped(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    generated = tmp_path / "generated-skills"
    stale = generated / "process-123-dead"
    source = stale / "invocation" / ECLAB_SKILL_NAME
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Stale\n", encoding="utf-8")
    (stale / ".owner.json").write_text('{"pid": 123, "token": "dead"}\n', encoding="utf-8")
    legacy = generated / ("a" * 64)
    legacy_skill = legacy / ECLAB_SKILL_NAME
    legacy_skill.mkdir(parents=True)
    (legacy_skill / "SKILL.md").write_text("# Legacy stale\n", encoding="utf-8")
    os.utime(legacy, (0, 0))

    skill_plugin = importlib.import_module("engulf_clab_develop_lab_skill.plugin")
    monkeypatch.setattr(skill_plugin, "_process_is_alive", lambda pid: False)
    _prune_stale_generated_processes(generated, keep="process-current")

    assert not stale.exists()
    assert not legacy.exists()


def test_help_and_internal_calls_do_not_request_schema_refresh() -> None:
    assert _skip_automatic_refresh((), {})
    assert _skip_automatic_refresh(("--help",), {})
    assert _skip_automatic_refresh(("deploy", "--help"), {})
    assert _skip_automatic_refresh(("help", "deploy"), {})
    assert _skip_automatic_refresh(("deploy",), {"ENGULF_INTERNAL_PROTOCOL": "1"})
    assert not _skip_automatic_refresh(("deploy", "-t", "lab.clab.yml"), {})


def test_provider_is_active_only_for_base_eclab() -> None:
    assert _is_eclab_application(ECLAB_APPLICATION)
    assert not _is_eclab_application(EXTERNAL_APPLICATION)


def test_explicit_install_requests_strict_schema_build_and_contributes_path(
    tmp_path: Path,
) -> None:
    plugin = DevelopLabSkillPlugin()
    api = _API(ECLAB_APPLICATION, tmp_path / "provider-state")
    invocation = Invocation(("install-skills", str(tmp_path)), Path.cwd(), {})

    assert plugin.before_goal(invocation, api) is None  # type: ignore[arg-type]
    requests = api.values["engulf_clab.schema.requests"]
    assert len(requests) == 1  # type: ignore[arg-type]
    assert requests[0].required is True  # type: ignore[index]
    api.values[SCHEMA_COMPILED_CONTEXT] = _bundle()

    result = plugin.after_goal(
        invocation,
        GoalResult.completed(),
        api,  # type: ignore[arg-type]
    )

    assert result.exit_code == 0
    paths = api.values[SKILL_PATHS_CONTEXT]
    assert len(paths) == 1  # type: ignore[arg-type]
    assert paths[0].name == ECLAB_SKILL_NAME  # type: ignore[index]
    assert api.values[SKILL_TEMPORARY_PATHS_CONTEXT] == paths
    assert paths[0].parent.parent.name.startswith("process-")  # type: ignore[index]
    assert paths[0].parent.parent.parent.name == "generated-skills"  # type: ignore[index]


def test_external_edition_does_not_publish_schema_or_skill(tmp_path: Path) -> None:
    plugin = DevelopLabSkillPlugin()
    api = _API(EXTERNAL_APPLICATION, tmp_path / "provider-state")
    invocation = Invocation(("install-skills", str(tmp_path)), Path.cwd(), {})

    assert plugin.before_goal(invocation, api) is None  # type: ignore[arg-type]
    result = plugin.after_goal(invocation, GoalResult.completed(), api)  # type: ignore[arg-type]

    assert result.exit_code == 0
    assert api.values == {}


def test_skill_contributor_declares_ordering_and_both_entrypoints() -> None:
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    data: dict[str, Any] = tomllib.loads(pyproject.read_text())
    dependencies = data["project"]["entry-points"][
        "engulf.plugins.v1.dependency.engulf_clab_develop_lab_skill"
    ]
    assert dependencies["engulf_clab.schema"] == "preprocess=after; postprocess=before"
    assert dependencies["engulf_clab.skill_collector"] == "preprocess=before; postprocess=after"
    for group in (
        "engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper",
        "engulf.plugins.v1.application.engulf_clab",
    ):
        assert data["project"]["entry-points"][group][PLUGIN_ID]
