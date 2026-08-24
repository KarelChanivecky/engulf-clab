import json
from pathlib import Path

from engulf_clab_develop_lab_skill.plugin import (
    MARKER_NAME,
    PLUGIN_ID,
    _installed_fingerprint,
    _skip_automatic_refresh,
    _write_static_skill,
    install_command,
    skill_name,
)


def test_help_invocations_do_not_trigger_automatic_schema_refresh() -> None:
    assert _skip_automatic_refresh((), {})
    assert _skip_automatic_refresh(("--help",), {})
    assert _skip_automatic_refresh(("deploy", "--help"), {})
    assert _skip_automatic_refresh(("help", "deploy"), {})
    assert _skip_automatic_refresh(("deploy",), {"ENGULF_INTERNAL_PROTOCOL": "1"})
    assert not _skip_automatic_refresh(("deploy", "-t", "lab.clab.yml"), {})


def test_edition_names_and_rendered_skill(tmp_path: Path) -> None:
    assert install_command("eclab-enterprise") == "install-develop-eclab-enterprise-lab-skill"
    assert skill_name("eclab-enterprise") == "develop-eclab-enterprise-lab"

    target = tmp_path / "skill"
    _write_static_skill(target, "develop-eclab-lab")

    definition = (target / "SKILL.md").read_text()
    agent = (target / "agents" / "openai.yaml").read_text()
    assert "name: develop-eclab-lab" in definition
    assert "eclab install-develop-eclab-lab-skill <CONFIG_ROOT>" in definition
    assert "compact `schema.yaml`" in definition
    assert "generated node-kind" in definition
    assert "full topology schema for validation" in definition
    assert "basic network diagnostics" in definition
    assert "Never assign, rename, or use `eth0`" in definition
    assert "## Choose WAN access deliberately" in definition
    assert "## Troubleshooting" in definition
    assert "## Diagnose in layers" in definition
    assert len(definition.split()) < 1000
    assert "$develop-eclab-lab" in agent
    assert "@@" not in definition + agent


def test_runtime_catalog_is_appended_with_skill_relative_paths(tmp_path: Path) -> None:
    target = tmp_path / "skill"
    catalog = b"# Installed lab runtime catalog\n\n## Task routing\n\n`plugins/example/schema.yaml` and `clab.schema.json`\n"

    _write_static_skill(
        target,
        "develop-eclab-lab",
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
    _write_static_skill(target, "develop-eclab-lab")
    runtime = target / "references" / "runtimes" / fingerprint
    runtime.mkdir(parents=True)
    manifest = {"fingerprint": fingerprint, "plugins": [], "node_kinds": None}
    (runtime / "manifest.json").write_text(json.dumps(manifest) + "\n")
    (runtime / "clab.schema.json").write_text("{}\n")
    (runtime / "catalog.json").write_text("{}\n")
    (runtime / "catalog.md").write_text("# Catalog\n")
    (target / "references" / "current.json").write_text(
        json.dumps({"fingerprint": fingerprint}) + "\n"
    )
    (target / MARKER_NAME).write_text(
        json.dumps(
            {
                "owner": PLUGIN_ID,
                "skill_name": "develop-eclab-lab",
                "fingerprint": fingerprint,
            }
        )
        + "\n"
    )

    assert _installed_fingerprint(target) == fingerprint
    (runtime / "catalog.json").unlink()
    assert _installed_fingerprint(target) is None
