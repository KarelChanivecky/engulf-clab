import io
import json
import os
import subprocess
import tarfile
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from engulf_clab_freeze.command import (
    _offline_bundle_defroster,
    _runtime_bundle_defroster,
    freeze,
)
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
from engulf_clab_schema_api import RequirementKind, RuntimeRequirement


def _open_self_extracting_archive(path: Path) -> tarfile.TarFile:
    data = path.read_bytes()
    marker = b"__ECLAB_ARCHIVE_BELOW__\n"
    payload_offset = data.index(marker) + len(marker)
    return tarfile.open(fileobj=io.BytesIO(data[payload_offset:]), mode="r:gz")


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
        document = yaml.safe_load(saved.extractfile("share/lab.clab.yml"))
        metadata = json.load(saved.extractfile("share/freeze.json"))["freeze"]
        launcher = saved.extractfile("share/run-eclab.sh").read().decode()
    assert "x-engulf-clab-freeze" not in document
    assert "share/freeze.json" in names
    assert metadata["format"] == 3
    assert (metadata["mode"], metadata["producer_edition"]) == ("lean", "eclab")
    assert "engulf-clab" in metadata["runtime_packages"]
    assert "pytest" not in metadata["runtime_packages"]
    assert not any(
        "wheelhouse/" in name or ".eclab-venv/" in name or "images/" in name
        for name in names
    )
    assert "share/requirements.freeze.txt" not in names
    assert "share/packages.freeze.txt" in names
    assert "exec eclab" in launcher
    assert ".eclab-check-host-requirements.sh" in launcher
    with tarfile.open(archive) as saved:
        readme = saved.extractfile("share/FREEZE-README.md").read().decode()
    assert readme.startswith("# Frozen eclab lab: lab.clab.yml (lean)")
    assert "./run-eclab.sh destroy -t lab.clab.yml" in readme
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
        patch(
            "engulf_clab_freeze.runtime._package_mismatches",
            return_value=["package demo is missing (frozen 1)"],
        ),
        patch(
            "engulf_clab_freeze.runtime.EclabRuntimeProvider.check_recipient",
            return_value=["Containerlab commit is missing (frozen abc)"],
        ),
    ):
        defrost(
            archive,
            target,
            prepare_runtime=False,
            prompt_licenses=False,
            initialize_env=False,
            environment={},
        )
        first = (target / "FREEZE-WARNINGS.txt").read_text()
        assert first.count("package demo") == 1
        assert first.count("Containerlab commit") == 1
        assert (
            "package demo"
            in json.loads((target / ".eclab-defrost.json").read_text())["notes"][0]
        )
        defrost(
            archive,
            target,
            force=True,
            prepare_runtime=False,
            prompt_licenses=False,
            initialize_env=False,
            environment={},
        )
        assert (target / "FREEZE-WARNINGS.txt").read_text() == first


def test_defrost_reports_missing_host_dependencies_without_failing(tmp_path, capsys):
    topology = _lab(tmp_path)
    archive = tmp_path / "share.tar.gz"
    freeze(
        topology,
        archive,
        environment={},
        requirements=(
            RuntimeRequirement(
                RequirementKind.HOST_TOOL,
                "docker",
                "Run the deployment containers.",
                ("deploy",),
            ),
        ),
    )
    target = tmp_path / "received"
    completed = subprocess.CompletedProcess(
        args=[],
        returncode=1,
        stdout="WARNING: missing dependency: docker (run labs; deploy)\n",
        stderr="",
    )
    with (
        patch("engulf_clab_freeze.runtime._package_mismatches", return_value=[]),
        patch(
            "engulf_clab_freeze.runtime.EclabRuntimeProvider.check_recipient",
            return_value=[],
        ),
        patch(
            "engulf_clab_freeze.defrost.subprocess.run", return_value=completed
        ) as run,
    ):
        assert defrost(
            archive,
            target,
            prepare_runtime=False,
            prompt_licenses=False,
            initialize_env=False,
            environment={},
        )

    assert run.call_args.args[0] == [
        "/bin/sh",
        str(target / ".eclab-check-host-requirements.sh"),
        "report",
    ]
    assert "WARNING: missing dependency: docker" in capsys.readouterr().err


def test_tool_comparison_checks_containerlab_json_and_vrnetlab_git(tmp_path):
    provider = EclabRuntimeProvider()
    expected = {
        "containerlab": {"version": "0.2", "commit": "abc"},
        "vrnetlab": {"revision": "def"},
    }
    with (
        patch(
            "engulf_clab_freeze.runtime._tool_paths",
            return_value=(Path("/bin/clab"), Path("/vrnetlab")),
        ),
        patch(
            "engulf_clab_freeze.runtime._containerlab_version",
            return_value={"version": "0.3", "commit": "xyz"},
        ),
        patch(
            "engulf_clab_freeze.runtime._git_identity", return_value={"revision": "123"}
        ),
    ):
        issues = provider.check_recipient(expected, {}, None)
    assert len(issues) == 3
    assert "Containerlab version" in issues[0]
    assert "Containerlab commit" in issues[1]
    assert "vrnetlab revision" in issues[2]


def test_runtime_archive_adds_lock_and_wheelhouse_without_images(tmp_path):
    topology = _lab(tmp_path)
    archive = tmp_path / "share.run"

    def wheels(root, packages, warnings):
        wheelhouse = root / "wheelhouse"
        wheelhouse.mkdir()
        (wheelhouse / "demo-1-py3-none-any.whl").write_bytes(b"wheel")
        return True

    with (
        patch(
            "engulf_clab_freeze.runtime.EclabRuntimeProvider.capture",
            return_value={
                "containerlab": {"version": "1", "commit": "abc"},
                "vrnetlab": {"revision": "def"},
            },
        ),
        patch("engulf_clab_freeze.command._download_wheels", side_effect=wheels),
        patch(
            "engulf_clab_freeze.runtime._tool_paths",
            return_value=(Path("/bin/clab"), Path("/vrnetlab")),
        ),
        patch(
            "engulf_clab_freeze.runtime._containerlab_version",
            return_value={"version": "1", "commit": "abc"},
        ),
        patch(
            "engulf_clab_freeze.runtime._git_identity", return_value={"revision": "def"}
        ),
        patch(
            "engulf_clab_freeze.command._bundle_offline_containerlab",
            side_effect=_bundle_clab,
        ),
        patch(
            "engulf_clab_freeze.command._bundle_offline_vrnetlab",
            side_effect=_bundle_vrnetlab,
        ),
        patch("engulf_clab_freeze.command._bundle_offline_runtime") as bundle_venv,
        patch("engulf_clab_freeze.command._download_python_wheels") as python_wheels,
    ):
        freeze(
            topology,
            archive,
            with_runtime=True,
            environment={},
            requirements=(
                RuntimeRequirement(
                    RequirementKind.HOST_TOOL,
                    "make",
                    "Build opted-in vrnetlab images from source.",
                    commands=("deploy",),
                ),
            ),
        )
    bundle_venv.assert_not_called()
    python_wheels.assert_called_once()
    with _open_self_extracting_archive(archive) as saved:
        outer_names = saved.getnames()
        inner_data = saved.extractfile("lab.tgz").read()
        runtime_names = [name for name in outer_names if name.startswith("runtime/")]
        defroster = saved.extractfile("defrost.sh").read().decode()
        with tarfile.open(fileobj=io.BytesIO(inner_data), mode="r:gz") as inner:
            names = inner.getnames()
            host_requirements = (
                inner.extractfile("share/.eclab-host-requirements.tsv").read().decode()
            )
            document = yaml.safe_load(inner.extractfile("share/lab.clab.yml"))
            metadata = json.load(inner.extractfile("share/freeze.json"))["freeze"]
            launcher = inner.extractfile("share/run-eclab.sh").read().decode()
            lab_readme = inner.extractfile("share/FREEZE-README.md").read().decode()
        revision = saved.extractfile(
            "runtime/tools/vrnetlab/.eclab-freeze-revision"
        ).read()
        runtime_launcher = saved.extractfile("runtime/run-eclab.sh").read().decode()
        readme = saved.extractfile("README.md").read().decode()
    assert "x-engulf-clab-freeze" not in document
    assert metadata["mode"] == "runtime"
    assert "lab.tgz" in outer_names
    assert "runtime/requirements.freeze.txt" in outer_names
    assert "share/.eclab-host-requirements.tsv" in names
    assert "share/.eclab-check-host-requirements.sh" in names
    assert "deploy\thost-tool\tmake\tBuild opted-in" in host_requirements
    assert "runtime/wheelhouse/demo-1-py3-none-any.whl" in outer_names
    assert not any("images/" in name for name in outer_names)
    assert "runtime verify" in launcher
    assert "unset CONTAINERLAB_VERSION VRNETLAB_VERSION" in launcher
    assert "pip install --no-index" in launcher
    assert "python-versions.freeze.txt" in launcher
    assert revision == b"def\n"
    assert "(runtime)" in lab_readme
    assert "ECLAB_PYTHON" in lab_readme
    assert "tools/containerlab/bin/containerlab" not in names
    assert "tools/vrnetlab/common/vrnetlab.py" not in names
    assert "runtime/tools/containerlab/bin/containerlab" in outer_names
    assert "runtime/tools/vrnetlab/common/vrnetlab.py" in outer_names
    assert "--eclab-build-venv" in runtime_launcher
    assert '! -x "$venv/bin/python"' in runtime_launcher
    assert 'defrost "$root/lab.tgz"' in defroster
    assert '! -x "$runtime/.eclab-venv/bin/python"' in defroster
    assert "ECLAB_FREEZE_RUNTIME" in defroster
    assert "license" in readme.lower()
    assert any(name.startswith("runtime/") for name in runtime_names)
    assert not any(".eclab-venv/" in name for name in names)


def test_runtime_bundle_defroster_builds_venv_then_forwards_defrost_options(tmp_path):
    bundle = tmp_path / "package"
    runtime = bundle / "runtime"
    runtime.mkdir(parents=True)
    (bundle / "lab.tgz").write_bytes(b"archive")
    capture = tmp_path / "invocation.txt"
    launcher = runtime / "run-eclab.sh"
    launcher.write_text(
        "#!/bin/sh\n"
        'cd "$(dirname "$0")"\n'
        '[ "$1" = --eclab-build-venv ] || exit 9\n'
        "mkdir -p .eclab-venv/bin\n"
        "cat > .eclab-venv/bin/python <<'EOF'\n"
        "#!/bin/sh\nexit 0\n"
        "EOF\n"
        "cat > .eclab-venv/bin/eclab <<'EOF'\n"
        "#!/bin/sh\n"
        'printf \'%s\\n\' "$ECLAB_FREEZE_RUNTIME" > "$TEST_CAPTURE"\n'
        'printf \'%s\\n\' "$@" >> "$TEST_CAPTURE"\n'
        "EOF\n"
        "chmod +x .eclab-venv/bin/python .eclab-venv/bin/eclab\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    defroster = bundle / "defrost.sh"
    defroster.write_text(_runtime_bundle_defroster("run-eclab.sh"), encoding="utf-8")
    defroster.chmod(0o755)

    result = subprocess.run(
        [
            str(defroster),
            "--eclab-output",
            "restored",
            "--eclab-license",
            "router=/pool",
        ],
        env={"TEST_CAPTURE": str(capture)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert capture.read_text(encoding="utf-8").splitlines() == [
        str(runtime),
        "defrost",
        str(bundle / "lab.tgz"),
        "--eclab-output",
        "restored",
        "--eclab-license",
        "router=/pool",
    ]


def test_runtime_bundle_rebuilds_when_python_is_missing_but_entrypoint_exists(
    tmp_path,
):
    bundle = tmp_path / "package"
    runtime = bundle / "runtime"
    binaries = runtime / ".eclab-venv" / "bin"
    binaries.mkdir(parents=True)
    (bundle / "lab.tgz").write_bytes(b"archive")
    capture = tmp_path / "invocation.txt"
    stale_entrypoint = binaries / "eclab"
    stale_entrypoint.write_text("#!/bin/sh\nexit 44\n", encoding="utf-8")
    stale_entrypoint.chmod(0o755)
    launcher = runtime / "run-eclab.sh"
    launcher.write_text(
        "#!/bin/sh\n"
        'cd "$(dirname "$0")"\n'
        '[ "$1" = --eclab-build-venv ] || exit 9\n'
        "mkdir -p .eclab-venv/bin\n"
        "printf '#!/bin/sh\\nexit 0\\n' > .eclab-venv/bin/python\n"
        "printf '#!/bin/sh\\n' > .eclab-venv/bin/eclab\n"
        "printf 'rebuilt\\n' >> \"$TEST_CAPTURE\"\n"
        "cat >> .eclab-venv/bin/eclab <<'EOF'\n"
        'printf \'%s\\n\' "$ECLAB_FREEZE_RUNTIME" >> "$TEST_CAPTURE"\n'
        'printf \'%s\\n\' "$@" >> "$TEST_CAPTURE"\n'
        "EOF\n"
        "chmod +x .eclab-venv/bin/python .eclab-venv/bin/eclab\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    defroster = bundle / "defrost.sh"
    defroster.write_text(_runtime_bundle_defroster("run-eclab.sh"), encoding="utf-8")
    defroster.chmod(0o755)

    result = subprocess.run(
        [str(defroster)],
        env={"TEST_CAPTURE": str(capture)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert capture.read_text(encoding="utf-8").splitlines() == [
        "rebuilt",
        str(runtime),
        "defrost",
        str(bundle / "lab.tgz"),
    ]


def test_offline_bundle_defroster_uses_copied_venv_and_forwards_options(tmp_path):
    bundle = tmp_path / "package"
    runtime = bundle / "runtime" / ".eclab-venv" / "bin"
    runtime.mkdir(parents=True)
    (bundle / "lab.tgz").write_bytes(b"archive")
    capture = tmp_path / "invocation.txt"
    edition = runtime / "eclab"
    edition.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$ECLAB_FREEZE_RUNTIME" > "$ECLAB_CAPTURE"\n'
        'printf \'%s\\n\' "$@" >> "$ECLAB_CAPTURE"\n',
        encoding="utf-8",
    )
    edition.chmod(0o755)
    defroster = bundle / "defrost.sh"
    defroster.write_text(_offline_bundle_defroster("eclab"), encoding="utf-8")
    defroster.chmod(0o755)

    result = subprocess.run(
        [str(defroster), "--eclab-output", "restored"],
        env={**os.environ, "ECLAB_CAPTURE": str(capture)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert capture.read_text(encoding="utf-8").splitlines() == [
        str(bundle / "runtime"),
        "defrost",
        str(bundle / "lab.tgz"),
        "--eclab-output",
        "restored",
    ]


def _bundle_clab(root, state, environment):
    (root / "tools" / "containerlab" / "bin").mkdir(parents=True)
    (root / "tools" / "containerlab" / "bin" / "containerlab").write_bytes(b"clab")


def _bundle_vrnetlab(root, state, environment):
    (root / "tools" / "vrnetlab" / "common").mkdir(parents=True)
    (root / "tools" / "vrnetlab" / "common" / "vrnetlab.py").write_bytes(b"vrnetlab")


def _bundled_lab(root, revision="123456789abc"):
    (root / ".eclab-venv" / "bin").mkdir(parents=True, exist_ok=True)
    (root / ".eclab-venv" / "bin" / "python").write_bytes(b"python")
    _bundle_clab(root, None, {})
    (root / "tools" / "containerlab" / "bin" / "containerlab").chmod(0o755)
    _bundle_vrnetlab(root, None, {})
    (root / "tools" / "vrnetlab" / ".eclab-freeze-revision").write_text(revision + "\n")


_RECORDED_TOOLS = {
    "containerlab": {
        "version": "1",
        "commit": "abcdef0",
        "repository": "https://example.org/containerlab.git",
        "revision": "abcdef012345",
    },
    "vrnetlab": {
        "revision": "123456789abc",
        "repository": "https://example.org/vrnetlab.git",
    },
}


def test_runtime_uses_bundled_tools_without_fetching(tmp_path):
    provider = EclabRuntimeProvider()
    _bundled_lab(tmp_path)
    with (
        patch(
            "engulf_clab_freeze.runtime._containerlab_version",
            return_value={"version": "1", "commit": "abcdef0"},
        ),
        patch("engulf_clab_freeze.runtime.subprocess.run") as run,
    ):
        provider.prepare_recipient(
            tmp_path,
            "runtime",
            _RECORDED_TOOLS,
            {
                "CONTAINERLAB_DIR": "/host/containerlab",
                "VRNETLAB_DIR": "/host/vrnetlab",
            },
            None,
            [],
        )
    run.assert_not_called()
    venv = tmp_path / ".eclab-venv"
    assert (venv / "bin" / "containerlab").read_bytes() == b"clab"
    assert (venv / "share" / "vrnetlab" / "common" / "vrnetlab.py").is_file()
    env = (tmp_path / ".eclab-freeze.env").read_text()
    assert f"CONTAINERLAB_BIN={venv}/bin/containerlab" in env
    assert f"VRNETLAB_DIR={venv}/share/vrnetlab" in env
    assert "VRNETLAB_UPDATE=0" in env
    assert "VRNETLAB_VERSION" not in env
    assert "CONTAINERLAB_VERSION" not in env
    assert "CONTAINERLAB_DIR" not in env
    assert "/host/" not in env
    assert not (tmp_path / ".eclab-runtime").exists()


def test_runtime_refuses_archive_without_bundled_containerlab(tmp_path):
    provider = EclabRuntimeProvider()
    with pytest.raises(DefrostError, match="virtual environment is missing"):
        provider.prepare_recipient(tmp_path, "runtime", _RECORDED_TOOLS, {}, None, [])
    (tmp_path / ".eclab-venv" / "bin").mkdir(parents=True)
    (tmp_path / ".eclab-venv" / "bin" / "python").write_bytes(b"python")
    with pytest.raises(DefrostError, match="no bundled Containerlab"):
        provider.prepare_recipient(tmp_path, "runtime", _RECORDED_TOOLS, {}, None, [])


def test_runtime_refuses_bundled_tools_that_differ_from_record(tmp_path):
    provider = EclabRuntimeProvider()
    _bundled_lab(tmp_path)
    with (
        patch(
            "engulf_clab_freeze.runtime._containerlab_version",
            return_value={"version": "2", "commit": "abcdef0"},
        ),
        pytest.raises(DefrostError, match="Containerlab identity differs"),
    ):
        provider.prepare_recipient(tmp_path, "runtime", _RECORDED_TOOLS, {}, None, [])
    (tmp_path / "tools" / "vrnetlab" / ".eclab-freeze-revision").write_text(
        "fedcba987654\n"
    )
    with (
        patch(
            "engulf_clab_freeze.runtime._containerlab_version",
            return_value={"version": "1", "commit": "abcdef0"},
        ),
        pytest.raises(DefrostError, match="vrnetlab revision differs"),
    ):
        provider.prepare_recipient(tmp_path, "runtime", _RECORDED_TOOLS, {}, None, [])


def test_runtime_freeze_refuses_changed_tools(tmp_path):
    provider = EclabRuntimeProvider()
    clab = {"version": "1", "commit": "abc"}
    with (
        patch(
            "engulf_clab_freeze.runtime._tool_paths",
            return_value=(Path("/bin/clab"), Path("/vrnetlab")),
        ),
        patch("engulf_clab_freeze.runtime._containerlab_version", return_value=clab),
        patch(
            "engulf_clab_freeze.runtime._git_identity",
            return_value={"revision": "other"},
        ),
        pytest.raises(
            Exception, match="vrnetlab changed while preparing the runtime archive"
        ),
    ):
        provider._bundle_tools(tmp_path, "runtime", clab, {"revision": "def"}, {}, None)


def test_runtime_archive_verification_requires_bundled_tools(tmp_path):
    (tmp_path / "requirements.freeze.txt").write_text("demo==1\n")
    (tmp_path / "wheelhouse").mkdir()
    (tmp_path / "wheelhouse" / "demo-1-py3-none-any.whl").write_bytes(b"wheel")
    with pytest.raises(DefrostError, match="no bundled Containerlab"):
        _verify_format_three_runtime(tmp_path, "runtime")
    _bundled_lab(tmp_path)
    _verify_format_three_runtime(tmp_path, "runtime")


def test_containerlab_version_reads_json_identity():
    result = type(
        "Result", (), {"returncode": 0, "stdout": '{"version":"0.2","gitCommit":"abc"}'}
    )()
    with patch("engulf_clab_freeze.runtime.subprocess.run", return_value=result) as run:
        assert _containerlab_version(Path("/bin/containerlab")) == {
            "version": "0.2",
            "commit": "abc",
        }
    assert run.call_args.args[0] == ["/bin/containerlab", "version", "-j"]


def test_extra_recipient_packages_do_not_mismatch(tmp_path):
    (tmp_path / "packages.freeze.txt").write_text("demo==1\n")
    with patch("importlib.metadata.version", return_value="1"):
        assert _package_mismatches(tmp_path, ["demo"]) == []


def test_lean_runtime_inventory_ignores_producer_development_tools(tmp_path):
    (tmp_path / "packages.freeze.txt").write_text(
        "engulf-clab==1\npytest==9\n", encoding="utf-8"
    )
    with patch("importlib.metadata.version", return_value="1") as version:
        assert _package_mismatches(tmp_path, ["engulf-clab"]) == []
    version.assert_called_once_with("engulf-clab")


def test_legacy_lean_archive_checks_engulf_packages_without_dev_tools(tmp_path):
    (tmp_path / "packages.freeze.txt").write_text(
        "engulf-clab==1\nengulf-clab-extra==1\npytest==9\n", encoding="utf-8"
    )
    with (
        patch(
            "engulf_clab_freeze.command._locked_packages",
            return_value=[("engulf-clab", "1")],
        ),
        patch(
            "importlib.metadata.version",
            side_effect=["1", PackageNotFoundError("engulf-clab-extra")],
        ) as version,
    ):
        assert _package_mismatches(tmp_path) == [
            "package engulf-clab-extra is missing (frozen 1)"
        ]
    assert version.call_count == 2


def test_offline_archive_layout_contains_bundled_components(tmp_path):
    topology = _lab(tmp_path)
    archive = tmp_path / "share.run"

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
        (root / "tools" / "vrnetlab" / "common" / "vrnetlab.py").write_bytes(
            b"vrnetlab"
        )

    with (
        patch(
            "engulf_clab_freeze.runtime.EclabRuntimeProvider.capture",
            return_value={
                "containerlab": {"version": "1", "commit": "abc"},
                "vrnetlab": {"revision": "def"},
            },
        ),
        patch(
            "engulf_clab_freeze.runtime._tool_paths",
            return_value=(Path("/bin/clab"), Path("/vrnetlab")),
        ),
        patch(
            "engulf_clab_freeze.runtime._containerlab_version",
            return_value={"version": "1", "commit": "abc"},
        ),
        patch(
            "engulf_clab_freeze.runtime._git_identity", return_value={"revision": "def"}
        ),
        patch("engulf_clab_freeze.command._download_wheels", side_effect=wheels),
        patch(
            "engulf_clab_freeze.command._bundle_offline_runtime",
            side_effect=bundle_runtime,
        ),
        patch(
            "engulf_clab_freeze.command._bundle_offline_containerlab",
            side_effect=bundle_clab,
        ),
        patch(
            "engulf_clab_freeze.command._bundle_offline_vrnetlab",
            side_effect=bundle_vrnetlab,
        ),
    ):
        freeze(topology, archive, offline=True, environment={})
    with _open_self_extracting_archive(archive) as saved:
        outer_names = saved.getnames()
        defroster = saved.extractfile("defrost.sh").read().decode()
        inner_data = saved.extractfile("lab.tgz").read()
    with tarfile.open(fileobj=io.BytesIO(inner_data), mode="r:gz") as saved:
        names = saved.getnames()
        record = json.load(saved.extractfile("share/freeze.json"))
        mode = record["freeze"]["mode"]
        document = yaml.safe_load(saved.extractfile("share/lab.clab.yml"))
        launcher = saved.extractfile("share/run-eclab.sh").read().decode()
    assert "x-engulf-clab-freeze" not in document
    assert mode == "offline"
    assert "runtime/.eclab-venv/bin/eclab" in outer_names
    assert 'defrost "$root/lab.tgz"' in defroster
    assert "ECLAB_FREEZE_RUNTIME" in defroster
    for name in (
        "share/FREEZE-README.md",
        "share/wheelhouse/demo-1-py3-none-any.whl",
        "share/tools/containerlab/bin/containerlab",
        "share/tools/vrnetlab/common/vrnetlab.py",
    ):
        assert name in names
    assert not any("/.eclab-venv/" in name for name in names)
    assert "pip install" not in launcher


def test_offline_archive_requires_complete_runtime_artifacts(tmp_path):
    (tmp_path / "requirements.freeze.txt").write_text("demo==1\n")
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    (wheelhouse / "demo-1-py3-none-any.whl").write_bytes(b"wheel")
    with (
        patch(
            "engulf_clab_freeze.defrost.subprocess.run",
            return_value=type("Result", (), {"returncode": 0})(),
        ),
        pytest.raises(DefrostError, match="complete .eclab-venv"),
    ):
        _verify_format_three_runtime(tmp_path, "offline")


def test_runtime_freeze_requires_complete_wheelhouse(tmp_path):
    provider = EclabRuntimeProvider()
    with (
        patch(
            "engulf_clab_freeze.command._locked_packages", return_value=[("demo", "1")]
        ),
        patch("engulf_clab_freeze.command._download_wheels", return_value=False),
        pytest.raises(Exception, match="requires a complete wheelhouse"),
    ):
        provider.prepare_archive(
            tmp_path,
            "runtime",
            {"containerlab": {"version": "1", "commit": "abc"}},
            {},
            None,
            [],
        )


def test_wheelhouse_records_only_resolvable_python_versions(tmp_path, monkeypatch):
    from engulf_clab_freeze import command

    (tmp_path / "wheelhouse").mkdir()
    (tmp_path / "wheelhouse" / "pure-1-py3-none-any.whl").write_bytes(b"")
    (
        tmp_path / "wheelhouse" / "cffi-2-cp314-cp314-manylinux_2_17_x86_64.whl"
    ).write_bytes(b"")
    monkeypatch.setattr(command.sys, "version_info", (3, 14, 0))
    failing = {"3.13"}

    def download(argv, **_):
        version = argv[argv.index("--python-version") + 1]
        return type("Result", (), {"returncode": 1 if version in failing else 0})()

    warnings = []
    with patch(
        "engulf_clab_freeze.command.subprocess.run", side_effect=download
    ) as run:
        assert command._download_python_wheels(tmp_path, warnings) == ["3.12", "3.14"]
    assert run.call_count == 2
    assert run.call_args.args[0][-1] == "cffi==2"
    assert (tmp_path / "python-versions.freeze.txt").read_text() == "3.12\n3.14\n"
    assert warnings == ["recipients cannot use Python 3.13: its wheels are unavailable"]


def test_defrost_selects_a_python_the_wheelhouse_supports(tmp_path):
    import sys

    from engulf_clab_freeze.defrost import _runtime_python

    assert _runtime_python(tmp_path) == sys.executable
    (tmp_path / "python-versions.freeze.txt").write_text("3.1\n")
    with pytest.raises(DefrostError, match="install one of: 3.1"):
        _runtime_python(tmp_path)
    current = f"{sys.version_info[0]}.{sys.version_info[1]}"
    (tmp_path / "python-versions.freeze.txt").write_text(f"{current}\n")
    assert _runtime_python(tmp_path) == sys.executable


def test_runtime_record_falls_back_to_separate_record_and_legacy_topology(tmp_path):
    from engulf_clab_freeze.runtime import _runtime_record

    record = {"format": 3, "mode": "runtime", "producer_edition": "eclab", "tools": {}}
    (tmp_path / "freeze.json").write_text(
        json.dumps({"version": 1, "topology": "lab.clab.yml", "freeze": record})
    )
    assert _runtime_record(tmp_path) == record
    (tmp_path / "freeze.json").unlink()
    (tmp_path / "lab.clab.yml").write_text(
        yaml.safe_dump({"name": "lab", "x-engulf-clab-freeze": record})
    )
    assert _runtime_record(tmp_path) == record
    (tmp_path / ".eclab-defrost.json").write_text(
        json.dumps({"freeze": {**record, "producer_edition": "fclab"}})
    )
    assert _runtime_record(tmp_path)["producer_edition"] == "fclab"


@pytest.mark.parametrize("mode", ["lean", "runtime", "offline"])
def test_every_mode_has_a_packaged_freeze_readme(mode):
    from engulf_clab_freeze.command import _freeze_readme

    readme = _freeze_readme(
        mode,
        topology_name="lab.clab.yml",
        edition="fclab",
        launcher_name="run-fclab.sh",
    )
    assert readme.startswith(f"# Frozen fclab lab: lab.clab.yml ({mode})")
    assert "./run-fclab.sh" in readme
    assert "$" not in readme


def test_freeze_readme_replaces_a_source_copy(tmp_path):
    topology = _lab(tmp_path)
    (topology.parent / "FREEZE-README.md").write_text(
        "stale guide from an earlier freeze\n"
    )
    archive = tmp_path / "share.tar.gz"
    freeze(topology, archive, environment={})
    with tarfile.open(archive) as saved:
        readme = saved.extractfile("share/FREEZE-README.md").read().decode()
    assert "stale guide" not in readme
    assert "(lean)" in readme


def _licensed_lab(tmp_path):
    topology = _lab(tmp_path)
    topology.write_text(
        yaml.safe_dump(
            {
                "name": "lab",
                "topology": {
                    "kinds": {
                        "fortinet_fortigate": {"license": "/private/pools/fortigate"}
                    },
                    "nodes": {
                        "fgt-1": {
                            "kind": "fortinet_fortigate",
                            "image": "example/fgt:1",
                        },
                        "client": {"kind": "linux", "image": "example/client:1"},
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return topology


def _readme(archive):
    with tarfile.open(archive) as saved:
        return saved.extractfile("share/FREEZE-README.md").read().decode()


def test_readme_explains_license_pools_for_licensed_nodes(tmp_path):
    topology = _licensed_lab(tmp_path)
    archive = tmp_path / "share.tar.gz"
    freeze(topology, archive, environment={})
    readme = _readme(archive)
    assert "## Licenses" in readme
    assert "- `fgt-1` (kind `fortinet_fortigate`)" in readme
    assert "`client`" not in readme
    assert (
        "eclab init-license-pool /path/to/fortinet_fortigate-licenses --kind fortinet_fortigate"
        in readme
    )
    assert "eclab defrost ARCHIVE.tar.gz --eclab-auto-license" in readme
    assert "`$VARIABLE`" in readme
    assert "/private/pools" not in readme
    assert "./run-eclab.sh init-license-pool" not in readme
    assert readme.index("## Licenses") < readme.index("## Operate")
    assert "\n\n\n" not in readme


def test_readme_omits_license_section_without_licensed_nodes(tmp_path):
    topology = _lab(tmp_path)
    archive = tmp_path / "share.tar.gz"
    freeze(topology, archive, environment={})
    readme = _readme(archive)
    assert "Licenses" not in readme
    assert "$licenses" not in readme
    assert "\n\n\n" not in readme


@pytest.mark.parametrize("mode", ["runtime", "offline"])
def test_bundled_readmes_register_pools_through_the_launcher(mode):
    from engulf_clab_freeze.command import _freeze_readme

    readme = _freeze_readme(
        mode,
        topology_name="lab.clab.yml",
        edition="eclab",
        launcher_name="run-eclab.sh",
        licensed_nodes=[("fgt-1", "fortinet_fortigate"), ("odd", None)],
    )
    assert (
        "./run-eclab.sh init-license-pool /path/to/fortinet_fortigate-licenses --kind fortinet_fortigate"
        in readme
    )
    assert "ECLAB_LICENSE=auto ./run-eclab.sh" in readme
    assert "- `odd` (kind not set; check the topology)" in readme
    assert "\n\n\n" not in readme
