import json
import tomllib
from pathlib import Path

import pytest

from engulf_clab_image_archive.config import build_requests_from_topology
from engulf_clab_image_archive.errors import ImageArchiveError
from engulf_clab_image_archive.freeze import image_sources


def test_freeze_discovery_entry_point_and_missing_archive(tmp_path):
    metadata = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert (
        metadata["project"]["entry-points"]["engulf_clab.freeze.images.v1"][
            "engulf_clab.image_archive"
        ]
        == "engulf_clab_image_archive.freeze:image_sources"
    )
    declarations = image_sources(
        tmp_path / "lab.clab.yml",
        {
            "topology": {
                "nodes": {
                    "router": {
                        "image": "router:1",
                        "env": {"ECLAB_IMAGE_ARCHIVE": "missing.tar.gz"},
                    }
                }
            }
        },
        {},
    )
    assert declarations[0].inputs[0].path == tmp_path / "missing.tar.gz"
    assert declarations[0].kind == "archive"


def test_shared_manifest_does_not_silently_choose_one_nodes_recipient_input(tmp_path):
    manifest = tmp_path / "images.json"
    variable = "ECLAB_FREEZE_BASE_ARCHIVE"
    manifest.write_text(
        json.dumps(
            {
                "format": 1,
                "images": [{"image": "base:1", "action": "archive", "archive_variable": variable}],
            }
        )
    )
    for name in ("one", "two"):
        (tmp_path / f"{name}.tar").write_bytes(b"archive")
    nodes = {
        name: {
            "image": f"{name}:1",
            "env": {"ECLAB_IMAGE_ARCHIVE_MANIFEST": "images.json", variable: f"{name}.tar"},
        }
        for name in ("one", "two")
    }
    with pytest.raises(ImageArchiveError, match="'one' and 'two'.*conflicting"):
        build_requests_from_topology(tmp_path / "lab.clab.yml", {"topology": {"nodes": nodes}})
