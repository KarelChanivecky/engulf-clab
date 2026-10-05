import tomllib
from pathlib import Path

from engulf_clab_vrnetlab_static_image_provider.freeze import image_sources


def test_freeze_discovery_does_not_invent_a_vm_image_environment_input(tmp_path):
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
                        },
                    }
                }
            },
        },
        {},
    )
    assert declarations[0].inputs == ()
    assert "ECLAB_VRNETLAB_TYPE" in declarations[0].controls


def test_freeze_discovery_ignores_a_source_from_invocation_environment(tmp_path):
    topology = tmp_path / "lab.clab.yml"
    document = {
        "name": "demo",
        "topology": {
            "nodes": {
                "router": {
                    "image": "router:1",
                    "env": {"ECLAB_VRNETLAB_TYPE": "vendor/router"},
                }
            }
        }
    }

    declarations = image_sources(
        topology,
        document,
        {"ECLAB_VRNETLAB_IMG_PATH": "/host/images/router.qcow2"},
    )

    assert declarations[0].inputs == ()
