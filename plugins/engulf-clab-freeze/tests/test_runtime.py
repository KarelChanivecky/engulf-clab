import json
import tarfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from engulf_clab_freeze.command import freeze
from engulf_clab_freeze.defrost import (
    DefrostError,
    _verify_format_three_runtime,
    defrost,
)
from engulf_clab_freeze.runtime import (
    EclabRuntimeProvider,
    _containerlab_version,
    _package_mismatches,
)
from engulf_clab_freeze_api import FreezeError as ProviderError


def _lab(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    topology = root / "lab.clab.yml"
    topology.write_text("topology: {nodes: {}}\n", encoding="utf-8")
    return topology


def test_lean_archive_layout_and_launcher(tmp_path):
    topology = _lab(tmp_path)
    archive = tmp_path / "share.tar.gz"
    freeze(topology, archive, environment={})
    with tarfile.open(archive) as saved:
        names = saved.getnames()
        metadata = yaml.safe_load(saved.extractfile("share/lab.clab.yml"))["x-engulf-clab-freeze"]
        launcher = saved.extractfile("share/run-eclab.sh").read().decode()
    assert metadata["format"] == 3
    assert (metadata["mode"], metadata["producer_edition"]) == ("lean", "eclab")
    assert not any("wheelhouse/" in name or ".eclab-venv/" in name or "images/" in name for name in names)
    assert "share/requirements.freeze.txt" not in names
    assert "share/packages.freeze.txt" in names
    assert "exec eclab" in launcher
    assert "pip install" not in launcher
    assert "freeze-compatible" not in launcher


def test_missing_producer_provider_fails_before_archive_creation(tmp_path):
    topology = _lab(tmp_path)
    archive = tmp_path / "share.tar.gz"
    with pytest.raises(ProviderError, match="no freeze runtime provider"):
        freeze(topology, archive, application_name="other-edition", environment={})
    assert not archive.exists()


def test_lean_defrost_reports_compatibility_only_once_and_force_regenerates(tmp_path):
    topology = _lab(tmp_path)
    archive = tmp_path / "share.tar.gz"
    freeze(topology, archive, environment={})
    target = tmp_path / "received"
    with (
        patch("engulf_clab_freeze.runtime._package_mismatches", return_value=["package demo is missing (frozen 1)"]),
        patch("engulf_clab_freeze.runtime.EclabRuntimeProvider.check_recipient", return_value=["Containerlab commit is missing (frozen abc)"]),
    ):
        defrost(archive, target, prepare_runtime=False, prompt_licenses=False, initialize_env=False, environment={})
        first = (target / "FREEZE-WARNINGS.txt").read_text()
        assert first.count("package demo") == 1
        assert first.count("Containerlab commit") == 1
        assert "package demo" in json.loads((target / ".eclab-defrost.json").read_text())["notes"][0]
        defrost(archive, target, force=True, prepare_runtime=False, prompt_licenses=False, initialize_env=False, environment={})
        assert (target / "FREEZE-WARNINGS.txt").read_text() == first


def test_tool_comparison_checks_containerlab_json_and_vrnetlab_git(tmp_path):
    provider = EclabRuntimeProvider()
    expected = {"containerlab": {"version": "0.2", "commit": "abc"}, "vrnetlab": {"revision": "def"}}
    with (
        patch("engulf_clab_freeze.runtime._tool_paths", return_value=(Path("/bin/clab"), Path("/vrnetlab"))),
        patch("engulf_clab_freeze.runtime._containerlab_version", return_value={"version": "0.3", "commit": "xyz"}),
        patch("engulf_clab_freeze.runtime._git_identity", return_value={"revision": "123"}),
    ):
        issues = provider.check_recipient(expected, {}, None)
    assert len(issues) == 3
    assert "Containerlab version" in issues[0]
    assert "Containerlab commit" in issues[1]
    assert "vrnetlab revision" in issues[2]


def test_runtime_archive_adds_lock_and_wheelhouse_without_images(tmp_path):
    topology = _lab(tmp_path)
    archive = tmp_path / "share.tar.gz"

    def wheels(root, packages, warnings):
        wheelhouse = root / "wheelhouse"
        wheelhouse.mkdir()
        (wheelhouse / "demo-1-py3-none-any.whl").write_bytes(b"wheel")
        return True

    with (
        patch("engulf_clab_freeze.runtime.EclabRuntimeProvider.capture", return_value={"containerlab": {"version": "1", "commit": "abc"}, "vrnetlab": {"revision": "def"}}),
        patch("engulf_clab_freeze.command._download_wheels", side_effect=wheels),
    ):
        freeze(topology, archive, with_runtime=True, environment={})
    with tarfile.open(archive) as saved:
        names = saved.getnames()
        metadata = yaml.safe_load(saved.extractfile("share/lab.clab.yml"))["x-engulf-clab-freeze"]
        launcher = saved.extractfile("share/run-eclab.sh").read().decode()
    assert metadata["mode"] == "runtime"
    assert "share/requirements.freeze.txt" in names
    assert "share/wheelhouse/demo-1-py3-none-any.whl" in names
    assert not any("images/" in name for name in names)
    assert "runtime verify" in launcher
    assert "pip install" in launcher


def test_runtime_refuses_mismatch_without_provisioning_source(tmp_path):
    provider = EclabRuntimeProvider()
    tools = {"containerlab": {"version": "1", "commit": "abc"}, "vrnetlab": {"revision": "def"}}
    with (
        patch("engulf_clab_freeze.runtime._tool_paths", return_value=(None, None)),
        pytest.raises(DefrostError, match="no safe repository"),
    ):
        provider.prepare_recipient(tmp_path, "runtime", tools, {}, None, [])


def test_runtime_provisions_recorded_tool_revisions_when_needed(tmp_path):
    provider = EclabRuntimeProvider()
    tools = {
        "containerlab": {"version": "1", "commit": "abcdef0", "repository": "https://example.org/containerlab.git", "revision": "abcdef012345"},
        "vrnetlab": {"revision": "123456789abc", "repository": "https://example.org/vrnetlab.git"},
    }
    with (
        patch("engulf_clab_freeze.runtime._tool_paths", return_value=(None, None)),
        patch("engulf_clab_freeze.runtime._clone_revision") as clone,
        patch("engulf_clab_freeze.runtime._containerlab_version", return_value={"version": "1", "commit": "abcdef0"}),
        patch("engulf_clab_freeze.runtime.subprocess.run", return_value=type("Result", (), {"returncode": 0})()),
    ):
        provider.prepare_recipient(tmp_path, "runtime", tools, {}, None, [])
    assert clone.call_count == 2
    env = (tmp_path / ".eclab-freeze.env").read_text()
    assert "CONTAINERLAB_BIN=" in env
    assert "VRNETLAB_DIR=" in env


def test_containerlab_version_reads_json_identity():
    result = type("Result", (), {"returncode": 0, "stdout": '{"version":"0.2","gitCommit":"abc"}'})()
    with patch("engulf_clab_freeze.runtime.subprocess.run", return_value=result) as run:
        assert _containerlab_version(Path("/bin/containerlab")) == {"version": "0.2", "commit": "abc"}
    assert run.call_args.args[0] == ["/bin/containerlab", "version", "-j"]


def test_extra_recipient_packages_do_not_mismatch(tmp_path):
    (tmp_path / "packages.freeze.txt").write_text("demo==1\n")
    with patch("importlib.metadata.version", return_value="1"):
        assert _package_mismatches(tmp_path) == []


def test_offline_archive_layout_contains_bundled_components(tmp_path):
    topology = _lab(tmp_path)
    archive = tmp_path / "share.tar.gz"

    def wheels(root, packages, warnings):
        (root / "wheelhouse").mkdir()
        (root / "wheelhouse" / "demo-1-py3-none-any.whl").write_bytes(b"wheel")
        return True

    def bundle_runtime(root, edition):
        (root / ".eclab-venv" / "bin").mkdir(parents=True)
        (root / ".eclab-venv" / "bin" / "python").write_bytes(b"python")
        (root / ".eclab-venv" / "bin" / edition).write_bytes(b"edition")

    def bundle_clab(root, state, environment):
        (root / "tools" / "containerlab" / "bin").mkdir(parents=True)
        (root / "tools" / "containerlab" / "bin" / "containerlab").write_bytes(b"clab")

    def bundle_vrnetlab(root, state, environment):
        (root / "tools" / "vrnetlab" / "common").mkdir(parents=True)
        (root / "tools" / "vrnetlab" / "common" / "vrnetlab.py").write_bytes(b"vrnetlab")

    with (
        patch("engulf_clab_freeze.runtime.EclabRuntimeProvider.capture", return_value={"containerlab": {"version": "1", "commit": "abc"}, "vrnetlab": {"revision": "def"}}),
        patch("engulf_clab_freeze.runtime._tool_paths", return_value=(Path("/bin/clab"), Path("/vrnetlab"))),
        patch("engulf_clab_freeze.runtime._containerlab_version", return_value={"version": "1", "commit": "abc"}),
        patch("engulf_clab_freeze.runtime._git_identity", return_value={"revision": "def"}),
        patch("engulf_clab_freeze.command._download_wheels", side_effect=wheels),
        patch("engulf_clab_freeze.command._bundle_offline_runtime", side_effect=bundle_runtime),
        patch("engulf_clab_freeze.command._bundle_offline_containerlab", side_effect=bundle_clab),
        patch("engulf_clab_freeze.command._bundle_offline_vrnetlab", side_effect=bundle_vrnetlab),
    ):
        freeze(topology, archive, offline=True, environment={})
    with tarfile.open(archive) as saved:
        names = saved.getnames()
        mode = yaml.safe_load(saved.extractfile("share/lab.clab.yml"))["x-engulf-clab-freeze"]["mode"]
        launcher = saved.extractfile("share/run-eclab.sh").read().decode()
    assert mode == "offline"
    for name in ("share/wheelhouse/demo-1-py3-none-any.whl", "share/.eclab-venv/bin/eclab", "share/tools/containerlab/bin/containerlab", "share/tools/vrnetlab/common/vrnetlab.py"):
        assert name in names
    assert "pip install" not in launcher


def test_offline_archive_requires_complete_runtime_artifacts(tmp_path):
    (tmp_path / "requirements.freeze.txt").write_text("demo==1\n")
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    (wheelhouse / "demo-1-py3-none-any.whl").write_bytes(b"wheel")
    with (
        patch("engulf_clab_freeze.defrost.subprocess.run", return_value=type("Result", (), {"returncode": 0})()),
        pytest.raises(DefrostError, match="complete .eclab-venv"),
    ):
        _verify_format_three_runtime(tmp_path, "offline")
