import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from engulf_clab_freeze_api import (
    FreezeError,
    ImageInput,
    ImageSource,
    discover_image_sources,
)
from engulf_clab_freeze_api.manifest import read_image_manifest, sha256


def test_image_declarations_are_immutable_and_validate_collections():
    source = ImageSource(
        "example:1", "node", "build", inputs=(ImageInput(Path("/file"), "INPUT"),)
    )
    with pytest.raises(FrozenInstanceError):
        source.image = "other:1"
    with pytest.raises(TypeError):
        ImageSource("example:1", None, "build", dependencies=["base:1"])
    with pytest.raises(ValueError):
        ImageInput(Path("relative"), "INPUT")


def test_discovery_is_deterministic_and_rejects_invalid_results(monkeypatch):
    call_order = []

    def entry(name):
        def collect(*args):
            call_order.append(name)
            return (ImageSource(name, None, "opaque"),)

        return SimpleNamespace(name=name, load=lambda: collect)

    monkeypatch.setattr(
        "engulf_clab_freeze_api.images.importlib.metadata.entry_points",
        lambda **kwargs: [entry("z:1"), entry("a:1")],
    )
    assert len(discover_image_sources(Path("/lab.yml"), {}, {})) == 2
    assert call_order == ["a:1", "z:1"]
    monkeypatch.setattr(
        "engulf_clab_freeze_api.images.importlib.metadata.entry_points",
        lambda **kwargs: [
            SimpleNamespace(name="invalid", load=lambda: lambda *args: (None,))
        ],
    )
    with pytest.raises(FreezeError, match="invalid"):
        discover_image_sources(Path("/lab.yml"), {}, {})


@pytest.mark.parametrize("path", ["../outside.tar", "/outside.tar"])
def test_manifest_rejects_escaping_archive_paths(tmp_path, path):
    manifest = tmp_path / "images.json"
    manifest.write_text(
        json.dumps(
            {
                "format": 1,
                "images": [
                    {
                        "image": "image:1",
                        "action": "archive",
                        "archive": path,
                        "sha256": "a" * 64,
                    }
                ],
            }
        )
    )
    with pytest.raises(FreezeError):
        read_image_manifest(manifest)


def test_manifest_hashes_shared_artifact_only_once(tmp_path, monkeypatch):
    archive = tmp_path / "image.tar"
    archive.write_bytes(b"image")
    checksum = sha256(archive)
    manifest = tmp_path / "images.json"
    manifest.write_text(
        json.dumps(
            {
                "format": 1,
                "images": [
                    {
                        "image": ref,
                        "action": "archive",
                        "archive": "image.tar",
                        "sha256": checksum,
                    }
                    for ref in ("one:1", "two:1")
                ],
            }
        )
    )
    hash_file = Mock(return_value=checksum)
    monkeypatch.setattr("engulf_clab_freeze_api.manifest.sha256", hash_file)
    assert len(read_image_manifest(manifest)) == 2
    hash_file.assert_called_once_with(archive)


def test_non_archive_decision_cannot_smuggle_an_archive_selection(tmp_path):
    manifest = tmp_path / "images.json"
    manifest.write_text(
        json.dumps(
            {
                "format": 1,
                "images": [
                    {
                        "image": "one:1",
                        "action": "registry",
                        "archive_variable": "ECLAB_FREEZE_ARCHIVE",
                    }
                ],
            }
        )
    )
    with pytest.raises(FreezeError, match="non-archive"):
        read_image_manifest(manifest)
