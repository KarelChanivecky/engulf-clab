import tomllib
from pathlib import Path

from engulf_clab_dockerfile_build.freeze import image_sources


def test_freeze_discovery_entry_point_and_inherited_recipe(tmp_path):
    metadata = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert (
        metadata["project"]["entry-points"]["engulf_clab.freeze.images.v1"][
            "engulf_clab.dockerfile_build"
        ]
        == "engulf_clab_dockerfile_build.freeze:image_sources"
    )
    (tmp_path / "Dockerfile").write_text("FROM debian:12\n")
    declarations = image_sources(
        tmp_path / "lab.clab.yml",
        {
            "topology": {
                "defaults": {
                    "image": "app:1",
                    "env": {"ECLAB_DOCKERFILE": "Dockerfile", "ECLAB_DOCKER_CTX": "."},
                },
                "nodes": {"app": {}},
            }
        },
        {},
    )
    assert declarations[0].node == "app"
    assert declarations[0].dependencies == ("debian:12",)
    assert declarations[0].rebuildable
    assert not declarations[0].offline_rebuildable
