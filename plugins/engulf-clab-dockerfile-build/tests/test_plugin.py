from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from engulf_clab_lab_parser import TopologySession, load_topology
from engulf_executable_wrapper_api import CallMode, PreparedCallEvent

from engulf_clab_dockerfile_build.plugin import DockerfilePlugin
from engulf_clab_dockerfile_build.topology import topology_path_from_args


class PluginHelpTest(unittest.TestCase):
    def test_default_topology_ignores_writer_residue(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            topology = root / "lab.clab.yml"
            topology.write_text("topology: {}\n", encoding="utf-8")
            (root / ".engulf-clab-lab-stale.clab.yml").write_text(
                "topology: {}\n", encoding="utf-8"
            )

            self.assertEqual(topology_path_from_args((), root), topology.resolve())

    def test_help_uses_fixed_prefix_regardless_of_edition(self) -> None:
        api = Mock()
        api.application.short_product_name = "vendor clab"
        api.application.product = "Vendor Containerlab"

        help_text = DockerfilePlugin().help(api)

        self.assertIn("Node YAML env fields", help_text)
        self.assertIn("ECLAB_DOCKERFILE", help_text)
        self.assertNotIn("FCLAB_DOCKERFILE", help_text)
        self.assertIn("literal built tag; variables are unsupported", help_text)
        self.assertIn(
            "Runtime environment:\n"
            "    ECLAB_DOCKER_BUILD_JOBS  Concurrent image builds (default: 2)",
            help_text,
        )

    @patch("engulf_clab_dockerfile_build.plugin.build_images")
    def test_prepare_builds_from_materialized_topology(self, build_images: Mock) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            topology = root / "lab.clab.yml"
            dockerfile = root / "Dockerfile"
            topology.write_text(
                "topology:\n  nodes:\n    packaged:\n"
                "      image: eclab.containers/host-connector:latest\n",
                encoding="utf-8",
            )
            dockerfile.write_text("FROM scratch\n", encoding="utf-8")
            session = TopologySession(topology, load_topology(topology))
            session.editor("collection-manager").add(
                ("topology", "nodes", "packaged", "env"),
                {
                    "ECLAB_DOCKERFILE": str(dockerfile),
                    "ECLAB_DOCKER_CTX": str(root),
                },
            )
            api = Mock()
            api.application.short_product_name = "eclab"
            api.application.product = "Engulf Containerlab"
            api.require_context.return_value = session

            DockerfilePlugin().prepare_call(
                PreparedCallEvent(
                    "containerlab",
                    ("deploy",),
                    ("deploy",),
                    CallMode.NORMAL,
                ),
                api,
            )

        requests = build_images.call_args.args[0]
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].image, "eclab.containers/host-connector:latest")


if __name__ == "__main__":
    unittest.main()
