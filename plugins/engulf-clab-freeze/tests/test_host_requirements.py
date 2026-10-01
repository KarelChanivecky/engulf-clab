from __future__ import annotations

import os
import subprocess

from engulf_clab_freeze.command import _launcher
from engulf_clab_freeze.host_requirements import write_host_requirements
from engulf_clab_schema_api import RequirementKind, RuntimeRequirement


def test_operation_preflight_only_blocks_declared_requirements(tmp_path):
    topology = {
        "topology": {
            "nodes": {
                "router": {
                    "image": "example/router:1",
                    "env": {"ECLAB_VRNETLAB_TYPE": "vendor/router"},
                }
            }
        }
    }
    requirements = (
        RuntimeRequirement(
            RequirementKind.HOST_TOOL,
            "eclab-test-missing-tool",
            "Install the example deployment tool.",
            ("deploy",),
        ),
        RuntimeRequirement(
            RequirementKind.HOST_LIBRARY,
            "libeclab-test-missing.so.999",
            "Install the example shared library.",
            ("deploy",),
        ),
    )
    root = tmp_path / "demo"
    root.mkdir()
    write_host_requirements(root, requirements, {}, topology)
    launcher = root / "run-eclab.sh"
    launcher.write_text(_launcher("lab.clab.yml", mode="lean"), encoding="utf-8")
    launcher.chmod(0o755)

    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    fake_eclab = binary_dir / "eclab"
    fake_eclab.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\"\n", encoding="utf-8")
    fake_eclab.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = f"{binary_dir}:{environment['PATH']}"

    inspect = subprocess.run(
        [str(launcher), "inspect"],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    deploy = subprocess.run(
        [str(launcher), "deploy"],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    report = subprocess.run(
        [str(root / "check-dependencies.sh"), "deploy"],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert inspect.returncode == 0, inspect.stderr
    assert inspect.stdout == "inspect\n"
    assert deploy.returncode != 0
    assert "missing dependency for deploy" in deploy.stderr
    assert report.returncode == 0
    assert "WARNING: missing dependency: eclab-test-missing-tool" in report.stdout
    assert "WARNING: missing dependency: libeclab-test-missing.so.999" in report.stdout


def test_requirement_resolution_uses_topology_features_and_supplied_artifacts(
    tmp_path,
):
    topology = {
        "topology": {
            "nodes": {
                "router": {
                    "image": "example/router:1",
                    "env": {"ECLAB_VRNETLAB_TYPE": "vendor/router"},
                }
            }
        }
    }
    requirements = (
        RuntimeRequirement(
            RequirementKind.HOST_TOOL, "docker", "Run containers.", ("deploy",)
        ),
        RuntimeRequirement(
            RequirementKind.HOST_TOOL,
            "go",
            "Build Containerlab.",
            ("deploy",),
            unless_artifacts=("containerlab-binary",),
        ),
        RuntimeRequirement(
            RequirementKind.HOST_TOOL,
            "make",
            "Build opted-in vrnetlab images from source.",
            ("deploy",),
            topology_features=("vrnetlab-image-build",),
            unless_artifacts=("vrnetlab-images",),
        ),
        RuntimeRequirement(
            RequirementKind.HOST_TOOL,
            "qemu-img",
            "Build vrnetlab images.",
            ("deploy",),
            topology_features=("vrnetlab-image-build",),
            unless_artifacts=("vrnetlab-images",),
        ),
        RuntimeRequirement(
            RequirementKind.HOST_TOOL,
            "not-for-vrnetlab",
            "Only for another feature.",
            ("deploy",),
            topology_features=("another-feature",),
        ),
    )
    root = tmp_path / "package"
    root.mkdir()
    frozen = {
        "image_plan": {"images": [{"image": "example/router:1", "action": "build"}]}
    }
    write_host_requirements(root, requirements, frozen, topology)
    first = (root / ".eclab-host-requirements.tsv").read_text()
    assert "deploy\thost-tool\tdocker\t" in first
    assert "deploy\thost-tool\tgo\t" in first
    assert "deploy\thost-tool\tmake\t" in first
    assert "deploy\thost-tool\tqemu-img\t" in first
    assert "not-for-vrnetlab" not in first

    ordinary_topology = {
        "topology": {"nodes": {"router": {"image": "example/router:1", "env": {}}}}
    }
    ordinary_root = tmp_path / "ordinary-package"
    ordinary_root.mkdir()
    write_host_requirements(ordinary_root, requirements, {}, ordinary_topology)
    ordinary = (ordinary_root / ".eclab-host-requirements.tsv").read_text()
    assert "\tmake\t" not in ordinary
    assert "\tqemu-img\t" not in ordinary

    bundled = {
        "image_plan": {
            "images": [
                {
                    "image": "example/router:1",
                    "action": "archive",
                    "archive": "images/router.tar",
                }
            ]
        }
    }
    runtime = tmp_path / "runtime"
    binary = runtime / "tools" / "containerlab" / "bin" / "containerlab"
    binary.parent.mkdir(parents=True)
    binary.write_text("bundled", encoding="utf-8")
    binary.chmod(0o755)
    vrnetlab = runtime / "tools" / "vrnetlab" / "common" / "vrnetlab.py"
    vrnetlab.parent.mkdir(parents=True)
    vrnetlab.write_text("bundled vrnetlab", encoding="utf-8")
    image_archive = root / "images" / "router.tar"
    image_archive.parent.mkdir(parents=True)
    image_archive.write_bytes(b"bundled image")
    write_host_requirements(
        root, requirements, bundled, topology, artifact_root=runtime
    )
    resolved = (root / ".eclab-host-requirements.tsv").read_text()
    assert "docker" in resolved
    assert "go" not in resolved
    assert "make" not in resolved
    assert "qemu-img" not in resolved


def test_local_vrnetlab_images_remove_make_from_the_preflight(tmp_path):
    topology = {
        "topology": {
            "nodes": {
                "router": {
                    "image": "example/router:1",
                    "env": {"ECLAB_VRNETLAB_TYPE": "vendor/router"},
                }
            }
        }
    }
    requirement = RuntimeRequirement(
        RequirementKind.HOST_TOOL,
        "make",
        "Build opted-in vrnetlab images from source.",
        ("deploy",),
        topology_features=("vrnetlab-image-build",),
        unless_artifacts=("vrnetlab-images",),
    )
    root = tmp_path / "lab"
    root.mkdir()
    write_host_requirements(root, (requirement,), {}, topology)
    docker_bin = tmp_path / "bin"
    docker_bin.mkdir()
    docker = docker_bin / "docker"
    docker.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    docker.chmod(0o755)
    environment = {"PATH": str(docker_bin)}

    available = subprocess.run(
        ["/bin/sh", str(root / ".eclab-check-host-requirements.sh"), "deploy"],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert available.returncode == 0
    docker.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    missing = subprocess.run(
        ["/bin/sh", str(root / ".eclab-check-host-requirements.sh"), "deploy"],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert missing.returncode != 0
    assert "missing dependency for deploy: make" in missing.stderr
