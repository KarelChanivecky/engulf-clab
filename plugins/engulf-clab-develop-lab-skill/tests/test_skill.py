from pathlib import Path

from engulf_clab_develop_lab_skill.plugin import _write_static_skill, install_command, skill_name


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
    assert "full topology schema for validation" in definition
    assert "basic network diagnostics" in definition
    assert "## Choose WAN access deliberately" in definition
    assert "## Troubleshooting" in definition
    assert "## Diagnose in layers" in definition
    assert len(definition.split()) < 800
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
