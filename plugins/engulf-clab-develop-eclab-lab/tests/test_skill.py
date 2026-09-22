import json
import shutil
import tomllib
from pathlib import Path
from typing import Any, Self, cast

from engulf_api import ApplicationMetadata, GoalResult, Invocation
from engulf_clab_schema_api import CompiledSchemaBundle

from engulf_clab_develop_lab_skill.plugin import (
    MARKER_NAME,
    PLUGIN_ID,
    DevelopLabSkillPlugin,
    _installed_fingerprint,
    _is_eclab_application,
    _prune_backups,
    _prune_runtimes,
    _skip_automatic_refresh,
    _write_static_skill,
    install_command,
    plugin,
    skill_name,
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


class _RecordingAPI:
    def lease(self, name: str) -> Self:
        del name
        return self

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        del args


def _bundle(fingerprint: str) -> CompiledSchemaBundle:
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
        catalog_markdown=b"# Catalog\n",
        references=(),
        pipeline_id="eclab",
    )


def test_help_invocations_do_not_trigger_automatic_schema_refresh() -> None:
    assert _skip_automatic_refresh((), {})
    assert _skip_automatic_refresh(("--help",), {})
    assert _skip_automatic_refresh(("deploy", "--help"), {})
    assert _skip_automatic_refresh(("help", "deploy"), {})
    assert _skip_automatic_refresh(("deploy",), {"ENGULF_INTERNAL_PROTOCOL": "1"})
    assert not _skip_automatic_refresh(("deploy", "-t", "lab.clab.yml"), {})


def test_static_eclab_names_and_rendered_skill(tmp_path: Path) -> None:
    assert install_command() == "install-develop-eclab-lab-skill"
    assert skill_name() == "develop-eclab-lab"

    target = tmp_path / "skill"
    _write_static_skill(target)

    definition = (target / "SKILL.md").read_text()
    agent = (target / "agents" / "openai.yaml").read_text()
    assert "name: develop-eclab-lab" in definition
    assert "eclab install-develop-eclab-lab-skill <CONFIG_ROOT>" in definition
    assert "compact\n   `schema.yaml`" in definition
    assert "generated node-kind" in definition
    assert "full topology schema for validation" in definition
    assert "Never assign, rename, or use `eth0`" in definition
    assert "## Diagnose in layers" in definition
    assert "Do not infer vendor behavior from the generic skill" in definition
    assert "do not fall back to another" in definition
    assert "FortiGate" not in definition
    assert len(definition.split()) < 1000
    assert "$develop-eclab-lab" in agent
    assert "@@" not in definition + agent


def test_runtime_catalog_is_appended_with_skill_relative_paths(tmp_path: Path) -> None:
    target = tmp_path / "skill"
    catalog = b"# Installed lab runtime catalog\n\n## Task routing\n\n`plugins/example/schema.yaml` and `clab.schema.json`\n"

    _write_static_skill(
        target,
        catalog_markdown=catalog,
        fingerprint="abc123",
    )

    definition = (target / "SKILL.md").read_text()
    assert "## Installed lab runtime catalog" in definition
    assert "### Task routing" in definition
    assert "`references/runtimes/abc123/plugins/example/schema.yaml`" in definition
    assert "`references/runtimes/abc123/clab.schema.json`" in definition


def test_installed_fingerprint_requires_a_complete_runtime(tmp_path: Path) -> None:
    fingerprint = "b" * 64
    target = tmp_path / "develop-eclab-lab"
    _write_static_skill(target)
    runtime = target / "references" / "runtimes" / fingerprint
    runtime.mkdir(parents=True)
    manifest = {
        "fingerprint": fingerprint,
        "pipeline": {"id": "eclab", "lineage": ["eclab"]},
        "plugins": [],
        "node_kinds": None,
    }
    (runtime / "manifest.json").write_text(json.dumps(manifest) + "\n")
    (runtime / "clab.schema.json").write_text("{}\n")
    (runtime / "catalog.json").write_text("{}\n")
    (runtime / "catalog.md").write_text("# Catalog\n")
    (target / "references" / "current.json").write_text(
        json.dumps({"fingerprint": fingerprint, "pipeline_id": "eclab"}) + "\n"
    )
    (target / MARKER_NAME).write_text(
        json.dumps(
            {
                "owner": PLUGIN_ID,
                "skill_name": "develop-eclab-lab",
                "pipeline_id": "eclab",
                "fingerprint": fingerprint,
            }
        )
        + "\n"
    )

    assert _installed_fingerprint(target) == fingerprint
    (runtime / "catalog.json").unlink()
    assert _installed_fingerprint(target) is None
    shutil.rmtree(runtime)
    assert _installed_fingerprint(target) is None


def test_prune_runtimes_keeps_active_bundle_and_unrecognized_entries(
    tmp_path: Path,
) -> None:
    runtimes = tmp_path / "runtimes"
    runtimes.mkdir()
    keep = "a" * 64
    old = "b" * 64
    (runtimes / keep).mkdir()
    (runtimes / old).mkdir()
    (runtimes / "notes").mkdir()
    link = runtimes / "linked"
    link.symlink_to(runtimes / old, target_is_directory=True)

    _prune_runtimes(runtimes, keep=keep)

    assert (runtimes / keep).is_dir()
    assert not (runtimes / old).exists()
    assert (runtimes / "notes").is_dir()
    assert link.is_symlink()


def test_install_discards_runtime_history_without_backing_it_up(tmp_path: Path) -> None:
    root = tmp_path / "config"
    root.mkdir()
    target = root / "skills" / skill_name()
    _write_static_skill(target)
    old_fingerprint = "a" * 64
    old_runtime = target / "references" / "runtimes" / old_fingerprint
    old_runtime.mkdir(parents=True)
    manifest = {
        "fingerprint": old_fingerprint,
        "pipeline": {"id": "eclab", "lineage": ["eclab"]},
        "plugins": [],
        "node_kinds": None,
    }
    (old_runtime / "manifest.json").write_text(json.dumps(manifest) + "\n")
    (old_runtime / "clab.schema.json").write_text("{}\n")
    (old_runtime / "catalog.json").write_text("{}\n")
    (old_runtime / "catalog.md").write_text("# Catalog\n")
    (target / "references" / "current.json").write_text(
        json.dumps({"fingerprint": old_fingerprint, "pipeline_id": "eclab"}) + "\n"
    )
    (target / MARKER_NAME).write_text(
        json.dumps(
            {
                "owner": PLUGIN_ID,
                "skill_name": skill_name(),
                "pipeline_id": "eclab",
                "fingerprint": old_fingerprint,
            }
        )
        + "\n"
    )

    new_fingerprint = "b" * 64
    plugin._install(cast(Any, _RecordingAPI()), root, skill_name(), _bundle(new_fingerprint))

    runtimes = target / "references" / "runtimes"
    assert {entry.name for entry in runtimes.iterdir()} == {new_fingerprint}
    backups = root / "skills" / f".{skill_name()}-backups"
    backup = next(entry for entry in backups.iterdir() if entry.is_dir())
    assert not (backup / "references" / "runtimes").exists()


def test_prune_backups_keeps_only_latest_backup(tmp_path: Path) -> None:
    backups = tmp_path / ".develop-eclab-lab-backups"
    backups.mkdir()
    old = backups / "100"
    latest = backups / "200"
    unexpected = backups / "notes"
    old.mkdir()
    latest.mkdir()
    unexpected.write_text("not a backup")

    _prune_backups(backups)

    assert list(backups.iterdir()) == [latest]


def test_prune_backups_keeps_newly_created_backup(tmp_path: Path) -> None:
    backups = tmp_path / ".develop-eclab-lab-backups"
    backups.mkdir()
    old = backups / "200"
    latest = backups / "100"
    old.mkdir()
    latest.mkdir()

    _prune_backups(backups, keep=latest)

    assert list(backups.iterdir()) == [latest]


def test_eclab_collector_is_inactive_for_an_external_edition() -> None:
    assert _is_eclab_application(ECLAB_APPLICATION)
    assert not _is_eclab_application(EXTERNAL_APPLICATION)

    class UntouchedAPI:
        application = EXTERNAL_APPLICATION

        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"external edition collector touched {name}")

    api = cast(Any, UntouchedAPI())
    invocation = Invocation(("install-develop-eclab-lab-skill", "/tmp"), Path.cwd(), {})
    assert plugin.before_goal(invocation, api) is None
    result = GoalResult.completed("unchanged")
    assert plugin.after_goal(invocation, result, api) is result

    class UntouchedRegistry:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"external edition registered {name}")

    plugin.register_arguments(cast(Any, UntouchedRegistry()), api)
    plugin.register_completions(cast(Any, UntouchedRegistry()), api)
    assert plugin.help(api) == ""


def test_dependency_is_declared_in_package_metadata() -> None:
    project_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    project = tomllib.loads(project_path.read_text(encoding="utf-8"))["project"]
    group = project["entry-points"][
        "engulf.plugins.v1.dependency.engulf_clab_develop_lab_skill"
    ]

    assert group == {"engulf_clab.schema": "preprocess=after; postprocess=before"}
    assert "plugin_dependencies" not in DevelopLabSkillPlugin.__dict__
