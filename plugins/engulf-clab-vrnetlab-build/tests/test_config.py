from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from engulf_clab_vrnetlab_build.config import (
    VRNETLAB_IMAGE_PATH,
    VRNETLAB_TYPE,
    build_requests_from_topology,
    normalize_env_component,
    resolve_image_expression,
    scoped_variable_names,
    vrnetlab_build_jobs,
)
from engulf_clab_vrnetlab_build.errors import VrnetlabError
from engulf_clab_vrnetlab_build.topology import topology_path_from_args


def topology(node: dict[str, object]) -> dict[str, object]:
    return {"name": "my-lab", "topology": {"nodes": {"edge-1": node}}}


class SourceConfigurationTest(unittest.TestCase):
    def test_runtime_build_job_limit(self) -> None:
        self.assertEqual(vrnetlab_build_jobs("eclab", {}), 2)
        self.assertEqual(
            vrnetlab_build_jobs("fclab", {"FCLAB_VRNETLAB_BUILD_JOBS": "3"}),
            3,
        )
        with self.assertRaisesRegex(VrnetlabError, "positive integer"):
            vrnetlab_build_jobs("eclab", {"ECLAB_VRNETLAB_BUILD_JOBS": "many"})

    def test_scoped_variable_precedence(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            data = topology(
                {
                    "image": "vrnetlab/vendor_router:1",
                    "env": {
                        VRNETLAB_TYPE: "vendor/router",
                        VRNETLAB_IMAGE_PATH: "$IMAGE_SOURCE",
                    },
                }
            )
            environ = {
                "MY_LAB_EDGE_1_IMAGE_SOURCE": "/images/node.qcow2",
                "MY_LAB_IMAGE_SOURCE": "/images/lab.qcow2",
                "IMAGE_SOURCE": "/images/global.qcow2",
            }

            requests = build_requests_from_topology(root / "lab.clab.yml", data, environ)

        self.assertEqual(requests[0].source, Path("/images/node.qcow2"))

    def test_scoped_variable_falls_back_to_lab_then_global(self) -> None:
        self.assertEqual(
            scoped_variable_names("my-lab", "edge-1", "image_source"),
            (
                "MY_LAB_EDGE_1_IMAGE_SOURCE",
                "MY_LAB_IMAGE_SOURCE",
                "IMAGE_SOURCE",
            ),
        )
        self.assertEqual(normalize_env_component("--my lab--"), "MY_LAB")

    def test_relative_literal_is_relative_to_topology(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            data = topology(
                {
                    "image": "vrnetlab/vendor_router:1",
                    "env": {
                        VRNETLAB_TYPE: "vendor/router",
                        VRNETLAB_IMAGE_PATH: "images/router.qcow2",
                    },
                }
            )

            requests = build_requests_from_topology(root / "lab.clab.yml", data, {})

            self.assertEqual(requests[0].source, root / "images/router.qcow2")

    def test_process_fallback_long_name_precedes_short_alias(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            data = topology(
                {
                    "image": "vrnetlab/vendor_router:1",
                    "env": {VRNETLAB_TYPE: "vendor/router"},
                }
            )
            requests = build_requests_from_topology(
                root / "lab.clab.yml",
                data,
                {
                    "ECLAB_VRNETLAB_IMG_PATH": "/images/long.qcow2",
                    "E_V_IMG_PATH": "/images/short.qcow2",
                },
            )

        self.assertEqual(requests[0].source, Path("/images/long.qcow2"))

    def test_edition_vendor_prefix_selects_its_environment_settings(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            data = topology(
                {
                    "image": "vrnetlab/vendor_router:1",
                    "env": {
                        "ACME_CLAB_VRNETLAB_TYPE": "vendor/router",
                        "ACME_CLAB_VRNETLAB_IMG_PATH": "/images/acme.qcow2",
                        "ECLAB_VRNETLAB_TYPE": "ignored/router",
                    },
                }
            )

            requests = build_requests_from_topology(
                root / "lab.clab.yml",
                data,
                {},
                application_name="acme-clab",
            )

        self.assertEqual(requests[0].builder_type, "vendor/router")
        self.assertEqual(requests[0].source, Path("/images/acme.qcow2"))

    def test_missing_referenced_variable_fails_with_candidates(self) -> None:
        with TemporaryDirectory() as directory:
            data = topology(
                {
                    "image": "vrnetlab/vendor_router:1",
                    "env": {
                        VRNETLAB_TYPE: "vendor/router",
                        VRNETLAB_IMAGE_PATH: "${IMAGE_SOURCE}",
                    },
                }
            )
            with self.assertRaisesRegex(VrnetlabError, "MY_LAB_EDGE_1_IMAGE_SOURCE"):
                build_requests_from_topology(Path(directory) / "lab.clab.yml", data, {})

    def test_nodes_without_type_are_ignored(self) -> None:
        data = topology({"image": "alpine:latest", "env": {VRNETLAB_IMAGE_PATH: "x"}})
        self.assertEqual(build_requests_from_topology(Path("lab.clab.yml"), data, {}), [])

    def test_topology_name_is_not_required_without_opted_in_nodes(self) -> None:
        data = {"topology": {"nodes": {"client": {"image": "alpine:latest"}}}}
        self.assertEqual(build_requests_from_topology(Path("lab.clab.yml"), data, {}), [])


class ImageExpressionTest(unittest.TestCase):
    def test_default_expression(self) -> None:
        self.assertEqual(
            resolve_image_expression("${ROUTER_IMAGE:=vrnetlab/router:1}", {}),
            "vrnetlab/router:1",
        )

    def test_environment_expression(self) -> None:
        self.assertEqual(
            resolve_image_expression("${ROUTER_IMAGE}", {"ROUTER_IMAGE": "r:2"}), "r:2"
        )

    def test_embedded_expression_is_rejected(self) -> None:
        with self.assertRaises(VrnetlabError):
            resolve_image_expression("vrnetlab/router:${VERSION}", {"VERSION": "1"})


class TopologyArgumentTest(unittest.TestCase):
    def test_explicit_topology_options(self) -> None:
        self.assertEqual(topology_path_from_args(("-t", "lab.yml")), Path("lab.yml"))
        self.assertEqual(topology_path_from_args(("--topology=lab.yml",)), Path("lab.yml"))


if __name__ == "__main__":
    unittest.main()
