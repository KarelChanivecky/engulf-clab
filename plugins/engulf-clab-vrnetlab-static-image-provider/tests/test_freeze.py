import tomllib
from pathlib import Path

from engulf_clab_vrnetlab_static_image_provider.freeze import image_sources


def test_freeze_discovery_entry_point_and_unresolved_input(tmp_path):
    metadata = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert (
        metadata["project"]["entry-points"]["engulf_clab.freeze.images.v1"][
            "engulf_clab.vrnetlab_static_image_provider"
        ]
        == "engulf_clab_vrnetlab_static_image_provider.freeze:image_sources"
    )
    declarations = image_sources(
        tmp_path / "lab.clab.yml",
        {
            "name": "demo",
            "topology": {
                "nodes": {
                    "router": {
                        "image": "router:1",
                        "env": {
                            "ECLAB_VRNETLAB_TYPE": "vendor/router",
                            "ECLAB_VRNETLAB_IMG_PATH": "$UNSET_SOURCE",
                        },
                    }
                }
            },
        },
        {},
    )
    assert declarations[0].inputs[0].path is None
    assert declarations[0].inputs[0].artifact
    assert "ECLAB_VRNETLAB_TYPE" in declarations[0].controls
