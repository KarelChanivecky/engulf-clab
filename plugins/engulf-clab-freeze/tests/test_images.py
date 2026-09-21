from __future__ import annotations

import copy
import io
import json
import shutil
import subprocess
import tarfile
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml
from engulf_clab_freeze.command import _write_environment_initializer, freeze, main
from engulf_clab_freeze.defrost import DefrostError, defrost
from engulf_clab_freeze.images import MANIFEST, freeze_images, registry_identity
from engulf_clab_freeze_api import FreezeError, ImageSource
from engulf_clab_freeze_api.manifest import read_image_manifest
from engulf_clab_image_archive.config import build_requests_from_topology
from engulf_clab_image_archive.provider import ImageArchiveProvider
from engulf_clab_lab_parser.session import load_topology
from engulf_docker_image_api import (
    DockerArchiveRecipe,
    ImageBuildGraph,
    ImageRequirement,
    RegisteredImageProvider,
)
from engulf_docker_image_core import resolve_image_graph


def saved_image(path: Path, tags=(), image_id="a" * 64):
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(
        [{"RepoTags": list(tags), "Config": image_id + ".json", "Layers": []}]
    ).encode()
    with tarfile.open(path, "w:gz" if path.name.endswith(".gz") else "w") as archive:
        member = tarfile.TarInfo("manifest.json")
        member.size = len(body)
        archive.addfile(member, io.BytesIO(body))


@pytest.fixture
def host(monkeypatch):
    local = {}
    remote = {"debian:12", "alpine:3"}
    commands = []

    def run(arguments, **kwargs):
        commands.append(arguments)
        assert arguments[:3] == ["docker", "image", "save"], arguments
        saved_image(Path(arguments[4]), image_id=arguments[5].removeprefix("sha256:"))
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(
        "engulf_clab_freeze.images.inspect_image",
        lambda reference: local.get(reference),
    )
    monkeypatch.setattr(
        "engulf_clab_freeze.images.registry_identity",
        lambda reference, _local: "sha256:" + "b" * 64 if reference in remote else None,
    )
    monkeypatch.setattr("engulf_clab_freeze.images._run", run)
    monkeypatch.setattr(
        "engulf_clab_freeze.command._download_wheels", lambda *args: None
    )
    return local, remote, commands


def available(host, reference, identity="a" * 64):
    host[0][reference] = {
        "Id": "sha256:" + identity,
        "Os": "linux",
        "Architecture": "amd64",
    }


def lab(tmp_path, nodes, *, defaults=None):
    root = tmp_path / "lab"
    root.mkdir()
    document = {"name": "demo", "topology": {"nodes": nodes}}
    if defaults:
        document["topology"]["defaults"] = defaults
    topology = root / "lab.clab.yml"
    topology.write_text(yaml.safe_dump(document))
    return topology, document


def plan(tmp_path, topology, document, **options):
    staging = tmp_path / "staging"
    shutil.copytree(topology.parent, staging)
    staged_document = copy.deepcopy(document)
    result = freeze_images(topology, staged_document, staging, {}, **options)
    (staging / topology.name).write_text(yaml.safe_dump(staged_document))
    return result, staged_document, staging


def test_registry_image_and_complete_derivative_are_not_exported(tmp_path, host):
    topology, document = lab(
        tmp_path,
        {
            "base": {"image": "debian:12"},
            "app": {
                "image": "app:1",
                "env": {
                    "ECLAB_DOCKERFILE": "app/Dockerfile",
                    "ECLAB_DOCKER_CTX": "app",
                },
            },
        },
    )
    (topology.parent / "app").mkdir()
    (topology.parent / "app/Dockerfile").write_text("FROM debian:12\nRUN echo hello\n")
    result, document, staging = plan(tmp_path, topology, document)
    assert {entry["image"]: entry["action"] for entry in result["images"]} == {
        "app:1": "build",
        "debian:12": "registry",
    }
    assert host[2] == []
    assert not (staging / "images").exists()


def test_external_archive_is_copied_once_and_bound_to_exact_references(tmp_path, host):
    external = tmp_path / "saved.tar.gz"
    saved_image(external, ("vendor/image:1",))
    topology, document = lab(
        tmp_path,
        {
            "one": {"image": "one:1"},
            "two": {"image": "two:1"},
        },
        defaults={
            "env": {
                "ECLAB_IMAGE_ARCHIVE": str(external),
                "ECLAB_IMAGE_ARCHIVE_REF": "vendor/image:1",
            }
        },
    )
    result, document, staging = plan(tmp_path, topology, document)
    entries = result["images"]
    assert len({entry["archive"] for entry in entries}) == 1
    assert host[2] == []
    assert str(external) not in yaml.safe_dump(document)
    requests = build_requests_from_topology(staging / topology.name, document)
    assert {request.image for request in requests} == {"one:1", "two:1"}
    assert all(request.source == "vendor/image:1" for request in requests)
    assert all(request.reload for request in requests)


def test_local_archive_is_not_duplicated(tmp_path, host):
    topology, document = lab(
        tmp_path,
        {"one": {"image": "one:1", "env": {"ECLAB_IMAGE_ARCHIVE": "input.tar"}}},
    )
    saved_image(topology.parent / "input.tar", ("one:1",))
    result, _, staging = plan(tmp_path, topology, document)
    assert result["images"][0]["archive"] == "input.tar"
    assert list(staging.glob("**/*.tar")) == [staging / "input.tar"]


@pytest.mark.parametrize("external", [True, False])
def test_vrnetlab_build_requires_included_qcow(tmp_path, host, external):
    topology, document = lab(
        tmp_path,
        {
            "router": {
                "image": "router:1",
                "env": {"ECLAB_VRNETLAB_TYPE": "vendor/router"},
            }
        },
    )
    disk = (tmp_path if external else topology.parent) / "disk.qcow2"
    disk.write_bytes(b"disk")
    document["topology"]["nodes"]["router"]["env"]["ECLAB_VRNETLAB_IMG_PATH"] = str(
        disk
    )
    available(host, "router:1")
    result, document, staging = plan(tmp_path, topology, document)
    entry = result["images"][0]
    env = document["topology"]["nodes"]["router"]["env"]
    if external:
        assert entry["action"] == "archive"
        assert "ECLAB_VRNETLAB_TYPE" not in env
        assert not list(staging.glob("**/*.qcow2"))
        assert host[2][0][-1] == "sha256:" + "a" * 64
    else:
        assert entry["action"] == "build"
        assert env["ECLAB_VRNETLAB_IMG_PATH"] == "disk.qcow2"
        assert host[2] == []


def test_offline_captures_build_outputs_without_network_or_qcow_requirement(
    tmp_path, host
):
    topology, document = lab(
        tmp_path,
        {
            "router": {
                "image": "router:1",
                "env": {"ECLAB_VRNETLAB_TYPE": "vendor/router"},
            }
        },
    )
    available(host, "router:1")
    result, document, _ = plan(tmp_path, topology, document, offline=True)
    assert result["images"][0]["action"] == "archive"
    assert "ECLAB_VRNETLAB_TYPE" not in document["topology"]["nodes"]["router"]["env"]


def test_recursive_local_base_is_manifest_provider_without_runtime_node(tmp_path, host):
    topology, document = lab(
        tmp_path,
        {
            "app": {
                "image": "app:1",
                "env": {
                    "ECLAB_DOCKERFILE": "app/Dockerfile",
                    "ECLAB_DOCKER_CTX": "app",
                },
            }
        },
    )
    (topology.parent / "app").mkdir()
    (topology.parent / "app/Dockerfile").write_text(
        "FROM private/base:1\nCOPY --from=alpine:3 /bin/sh /sh\n"
    )
    available(host, "private/base:1")
    result, document, staging = plan(tmp_path, topology, document)
    assert {entry["image"]: entry["action"] for entry in result["images"]} == {
        "app:1": "build",
        "private/base:1": "archive",
        "alpine:3": "registry",
    }
    provider = ImageArchiveProvider()
    provider.refresh_requests(
        build_requests_from_topology(staging / topology.name, document)
    )
    resolved = resolve_image_graph(
        ImageBuildGraph((ImageRequirement("private/base:1"),)),
        (RegisteredImageProvider("example.archive", provider),),
    )
    assert isinstance(resolved.images[0].provision.recipe, DockerArchiveRecipe)
    assert list(document["topology"]["nodes"]) == ["app"]


def test_missing_input_after_exclusions_captures_output(tmp_path, host):
    topology, document = lab(
        tmp_path,
        {
            "app": {
                "image": "app:1",
                "env": {
                    "ECLAB_DOCKERFILE": "app/Dockerfile",
                    "ECLAB_DOCKER_CTX": "app",
                },
            }
        },
    )
    (topology.parent / "app").mkdir()
    (topology.parent / "app/Dockerfile").write_text(
        "FROM debian:12\nCOPY secret.txt /input\n"
    )
    (topology.parent / "app/secret.txt").write_text("input")
    (topology.parent / ".eclab-freezeignore").write_text("app/secret.txt\n")
    available(host, "app:1")
    archive = tmp_path / "bundle.tar.gz"
    freeze(topology, archive, environment={})
    with tarfile.open(archive) as saved:
        document = yaml.safe_load(saved.extractfile("bundle/lab.clab.yml"))
        assert "ECLAB_DOCKERFILE" not in document["topology"]["nodes"]["app"]["env"]
        assert "bundle/app/secret.txt" not in saved.getnames()


def test_unknown_missing_image_fails_atomically_with_consumer(tmp_path, host):
    topology, document = lab(tmp_path, {"router": {"image": "unknown:1"}})
    archive = tmp_path / "bundle.tar.gz"
    with pytest.raises(FreezeError, match="unknown:1"):
        freeze(topology, archive, environment={})
    assert not archive.exists()
    assert yaml.safe_load(topology.read_text()) == document


def test_export_deduplicates_aliases_by_image_identity(tmp_path, host):
    topology, document = lab(
        tmp_path, {"one": {"image": "one:1"}, "two": {"image": "two:1"}}
    )
    available(host, "one:1")
    available(host, "two:1")
    result, _, _ = plan(tmp_path, topology, document)
    assert len(host[2]) == 1
    assert len({entry["archive"] for entry in result["images"]}) == 1


@pytest.mark.parametrize("kind", ["archive", "vrnetlab", "opaque"])
def test_lean_replaces_inputs_with_variables_without_exporting(tmp_path, host, kind):
    env = {}
    if kind == "archive":
        saved_image(tmp_path / "input.tar", ("router:1",))
        env = {"ECLAB_IMAGE_ARCHIVE": str(tmp_path / "input.tar")}
    elif kind == "vrnetlab":
        env = {
            "ECLAB_VRNETLAB_TYPE": "vendor/router",
            "ECLAB_VRNETLAB_IMG_PATH": str(tmp_path / "missing.qcow2"),
        }
    topology, document = lab(
        tmp_path,
        {"router": {"image": "router:1", "env": env}, "public": {"image": "debian:12"}},
    )
    _, document, staging = plan(tmp_path, topology, document, lean=True)
    serialized = yaml.safe_dump(document)
    assert "${ECLAB_FREEZE_" in serialized
    assert str(tmp_path) not in serialized
    assert host[2] == []
    assert document["topology"]["nodes"]["public"]["image"] == "debian:12"
    assert not (staging / "images").exists()
    _write_environment_initializer(staging / topology.name, staging)
    assert "ECLAB_FREEZE_ROUTER" in (staging / "initialize-env.sh").read_text()


def test_lean_omits_lab_local_binary_input(tmp_path, host):
    topology, document = lab(
        tmp_path,
        {"router": {"image": "router:1", "env": {"ECLAB_IMAGE_ARCHIVE": "input.tar"}}},
    )
    saved_image(topology.parent / "input.tar", ("router:1",))
    _, _, staging = plan(tmp_path, topology, document, lean=True)
    assert not (staging / "input.tar").exists()
    assert (topology.parent / "input.tar").exists()


def test_lean_recursive_missing_base_gets_recipient_archive_variable(tmp_path, host):
    topology, document = lab(
        tmp_path,
        {
            "app": {
                "image": "app:1",
                "env": {
                    "ECLAB_DOCKERFILE": "app/Dockerfile",
                    "ECLAB_DOCKER_CTX": "app",
                },
            }
        },
    )
    (topology.parent / "app").mkdir()
    (topology.parent / "app/Dockerfile").write_text("FROM private/base:1\n")
    result, document, staging = plan(tmp_path, topology, document, lean=True)
    dependency = next(
        entry for entry in result["images"] if entry["image"] == "private/base:1"
    )
    variable = dependency["archive_variable"]
    assert (
        document["topology"]["nodes"]["app"]["env"][variable] == "${" + variable + "}"
    )
    archive = tmp_path / "recipient.tar"
    saved_image(archive, ("private/base:1",))
    restored = load_topology(staging / topology.name, {variable: str(archive)})
    assert (
        build_requests_from_topology(staging / topology.name, restored)[0].archive
        == archive
    )


def test_override_can_declare_external_or_force_snapshot(tmp_path, host):
    topology, document = lab(
        tmp_path, {"one": {"image": "private:1"}, "two": {"image": "debian:12"}}
    )
    available(host, "debian:12")
    result, _, _ = plan(
        tmp_path,
        topology,
        document,
        external_images=("private:1",),
        bundle_images=("debian:12",),
    )
    assert {entry["image"]: entry["action"] for entry in result["images"]} == {
        "debian:12": "archive",
        "private:1": "external",
    }


def test_lean_and_offline_are_incompatible(tmp_path, host):
    topology, _ = lab(tmp_path, {})
    assert main(["-t", str(topology), "--lean", "--offline"]) == 1


def test_freeze_defrost_roundtrip_needs_no_docker_at_restore(
    tmp_path, host, monkeypatch
):
    topology, original = lab(
        tmp_path,
        {
            "router": {
                "image": "router:1",
                "env": {"ECLAB_VRNETLAB_TYPE": "vendor/router"},
            }
        },
    )
    available(host, "router:1")
    archive = tmp_path / "bundle.tar.gz"
    freeze(topology, archive, environment={})
    monkeypatch.setattr(
        "engulf_clab_freeze.defrost.subprocess.run",
        Mock(side_effect=AssertionError("unexpected Docker call")),
    )
    target = tmp_path / "restored"
    defrost(
        archive,
        target,
        prepare_runtime=False,
        prompt_licenses=False,
        initialize_env=False,
        environment={},
    )
    restored = load_topology(target / topology.name, {})
    assert "x-engulf-clab-freeze" not in restored
    requests = build_requests_from_topology(target / topology.name, restored)
    assert requests[0].image == "router:1"
    assert "ECLAB_VRNETLAB_TYPE" not in restored["topology"]["nodes"]["router"]["env"]
    assert yaml.safe_load(topology.read_text()) == original


def test_manifest_integrity_failure_prevents_defrost_publication(tmp_path, host):
    topology, document = lab(tmp_path, {"router": {"image": "router:1"}})
    available(host, "router:1")
    result, document, staging = plan(tmp_path, topology, document)
    (staging / result["images"][0]["archive"]).write_bytes(b"tampered")
    with pytest.raises(FreezeError, match="checksum mismatch"):
        read_image_manifest(staging / MANIFEST)


def test_registry_probe_rejects_same_tag_with_different_local_content(monkeypatch):
    payload = {
        "Descriptor": {"digest": "sha256:" + "b" * 64},
        "SchemaV2Manifest": {"config": {"digest": "sha256:" + "a" * 64}},
    }
    monkeypatch.setattr(
        "engulf_clab_freeze.images._run",
        lambda *args: subprocess.CompletedProcess([], 0, json.dumps(payload), ""),
    )
    assert registry_identity("debian:12", {"Id": "sha256:" + "c" * 64}) is None
    assert (
        registry_identity("debian:12", {"Id": "sha256:" + "a" * 64})
        == "sha256:" + "b" * 64
    )


def test_custom_image_owner_can_declare_recursive_build(tmp_path, host, monkeypatch):
    topology, document = lab(tmp_path, {"app": {"image": "app:1"}})
    monkeypatch.setattr(
        "engulf_clab_freeze.images.discover_image_sources",
        lambda *args: (
            ImageSource(
                "app:1",
                "app",
                "build",
                dependencies=("private/base:1",),
                rebuildable=True,
            ),
        ),
    )
    available(host, "private/base:1")
    result, _, _ = plan(tmp_path, topology, document)
    assert {entry["image"]: entry["action"] for entry in result["images"]} == {
        "app:1": "build",
        "private/base:1": "archive",
    }


def test_missing_archive_uses_local_image_or_lean_variable(tmp_path, host):
    topology, document = lab(
        tmp_path,
        {
            "router": {
                "image": "router:1",
                "env": {"ECLAB_IMAGE_ARCHIVE": str(tmp_path / "missing.tar")},
            }
        },
    )
    available(host, "router:1")
    result, _, _ = plan(tmp_path, topology, document)
    assert result["images"][0]["action"] == "archive"
    assert len(host[2]) == 1
    lean_staging = tmp_path / "lean"
    shutil.copytree(topology.parent, lean_staging)
    freeze_images(topology, document, lean_staging, {}, lean=True)
    assert document["topology"]["nodes"]["router"]["env"][
        "ECLAB_IMAGE_ARCHIVE"
    ].startswith("${ECLAB_FREEZE_")
    assert len(host[2]) == 1


def test_lean_preserves_existing_unset_vm_variable(tmp_path, host):
    topology, document = lab(
        tmp_path,
        {
            "router": {
                "image": "router:1",
                "env": {
                    "ECLAB_VRNETLAB_TYPE": "vendor/router",
                    "ECLAB_VRNETLAB_IMG_PATH": "${MY_VM_INPUT}",
                },
            }
        },
    )
    _, document, _ = plan(tmp_path, topology, document, lean=True)
    assert (
        document["topology"]["nodes"]["router"]["env"]["ECLAB_VRNETLAB_IMG_PATH"]
        == "${MY_VM_INPUT}"
    )


def test_inherited_vrnetlab_recipe_is_disabled_at_every_origin(tmp_path, host):
    topology, document = lab(
        tmp_path,
        {"router": {}},
        defaults={
            "image": "router:1",
            "env": {
                "ECLAB_VRNETLAB_TYPE": "vendor/router",
                "ECLAB_VRNETLAB_IMG_PATH": "/missing.qcow2",
            },
        },
    )
    document["topology"]["groups"] = {
        "unused": {
            "env": {
                "ECLAB_VRNETLAB_TYPE": "unused/type",
                "ECLAB_VRNETLAB_IMG_PATH": "/unused.qcow2",
            }
        }
    }
    available(host, "router:1")
    _, document, _ = plan(tmp_path, topology, document)
    assert "ECLAB_VRNETLAB_TYPE" not in yaml.safe_dump(document)
    assert "/missing.qcow2" not in yaml.safe_dump(document)
    assert "/unused.qcow2" not in yaml.safe_dump(document)


def test_captured_build_only_node_is_removed_but_base_recipe_is_available(
    tmp_path, host
):
    external = tmp_path / "external"
    external.mkdir()
    (external / "Dockerfile").write_text("FROM debian:12\n")
    topology, document = lab(
        tmp_path,
        {
            "base": {
                "image": "base:1",
                "env": {
                    "ECLAB_DOCKERFILE": str(external / "Dockerfile"),
                    "ECLAB_DOCKER_CTX": str(external),
                    "ECLAB_DOCKER_BASE_NODE": "true",
                },
            },
            "app": {
                "image": "app:1",
                "env": {
                    "ECLAB_DOCKERFILE": "app/Dockerfile",
                    "ECLAB_DOCKER_CTX": "app",
                },
            },
        },
    )
    (topology.parent / "app").mkdir()
    (topology.parent / "app/Dockerfile").write_text("FROM base:1\n")
    available(host, "base:1")
    _, document, staging = plan(tmp_path, topology, document)
    assert set(document["topology"]["nodes"]) == {"app"}
    assert (
        build_requests_from_topology(staging / topology.name, document)[0].image
        == "base:1"
    )


def test_refreeze_reuses_recognized_manifest_and_archive(tmp_path, host):
    topology, document = lab(tmp_path, {"router": {"image": "router:1"}})
    available(host, "router:1")
    _, document, staging = plan(tmp_path, topology, document)
    destination = tmp_path / "again"
    shutil.copytree(staging, destination)
    result = freeze_images(staging / topology.name, document, destination, {})
    assert result["images"][0]["action"] == "archive"
    assert len(host[2]) == 1
    assert len(list(destination.glob("images/*.tar"))) == 1


def test_defrost_load_images_restores_tags_and_deduplicates_loads(
    tmp_path, host, monkeypatch
):
    topology, _ = lab(tmp_path, {"one": {"image": "one:1"}, "two": {"image": "two:1"}})
    available(host, "one:1")
    available(host, "two:1")
    archive = tmp_path / "bundle.tar.gz"
    freeze(topology, archive, environment={})
    calls = []

    def run(arguments, **kwargs):
        calls.append(arguments)
        return subprocess.CompletedProcess(
            arguments, 0, "Loaded image ID: sha256:" + "a" * 64 + "\n", ""
        )

    monkeypatch.setattr("engulf_clab_freeze.defrost.subprocess.run", run)
    defrost(
        archive,
        tmp_path / "restored",
        prepare_runtime=False,
        prompt_licenses=False,
        initialize_env=False,
        load_images=True,
        environment={},
    )
    assert sum(arguments[:3] == ["docker", "image", "load"] for arguments in calls) == 1
    assert {
        arguments[-1]
        for arguments in calls
        if arguments[:3] == ["docker", "image", "tag"]
    } == {"one:1", "two:1"}


def test_corrupt_manifest_archive_fails_before_defrost_publication(tmp_path, host):
    topology, _ = lab(tmp_path, {"router": {"image": "router:1"}})
    available(host, "router:1")
    archive = tmp_path / "bundle.tar.gz"
    freeze(topology, archive, environment={})
    extracted = tmp_path / "extracted"
    with tarfile.open(archive) as saved:
        saved.extractall(extracted, filter="data")
    root = extracted / "bundle"
    next(root.glob("images/*.tar")).write_bytes(b"modified")
    corrupt = tmp_path / "corrupt.tar.gz"
    with tarfile.open(corrupt, "w:gz") as saved:
        saved.add(root, arcname="bundle")
    into = tmp_path / "restored"
    with pytest.raises(DefrostError, match="checksum mismatch"):
        defrost(
            corrupt,
            into,
            prepare_runtime=False,
            prompt_licenses=False,
            initialize_env=False,
            environment={},
        )
    assert not into.exists()


def test_conflicting_recipes_for_shared_tag_are_rejected(tmp_path, host):
    one, two = tmp_path / "one.tar", tmp_path / "two.tar"
    saved_image(one, ("router:1",))
    saved_image(two, ("router:1",), "b" * 64)
    topology, document = lab(
        tmp_path,
        {
            "one": {"image": "router:1", "env": {"ECLAB_IMAGE_ARCHIVE": str(one)}},
            "two": {"image": "router:1", "env": {"ECLAB_IMAGE_ARCHIVE": str(two)}},
        },
    )
    with pytest.raises(FreezeError, match="conflicting acquisition"):
        plan(tmp_path, topology, document)


def test_dependency_cycle_names_the_chain(tmp_path, host, monkeypatch):
    topology, document = lab(tmp_path, {"one": {"image": "one:1"}})
    monkeypatch.setattr(
        "engulf_clab_freeze.images.discover_image_sources",
        lambda *args: (
            ImageSource(
                "one:1", "one", "build", dependencies=("two:1",), rebuildable=True
            ),
            ImageSource(
                "two:1", None, "build", dependencies=("one:1",), rebuildable=True
            ),
        ),
    )
    with pytest.raises(FreezeError, match="one:1 -> two:1 -> one:1"):
        plan(tmp_path, topology, document)


def test_digest_image_cannot_produce_an_unrestorable_archive_tag(tmp_path, host):
    reference = "router@sha256:" + "a" * 64
    topology, document = lab(tmp_path, {"one": {"image": reference}})
    available(host, reference)
    with pytest.raises(FreezeError, match="select a tag"):
        plan(tmp_path, topology, document)
    assert host[2] == []
