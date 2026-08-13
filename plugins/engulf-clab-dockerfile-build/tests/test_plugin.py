from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from engulf_clab_lab_parser import TopologySession, load_topology
from engulf_executable_wrapper_api import CallMode, PreparedCallEvent

from engulf_clab_dockerfile_build.plugin import DockerfilePlugin


class PluginHelpTest(unittest.TestCase):
    def test_help_distinguishes_node_fields_from_runtime_job_limit(self) -> None:
        api = Mock()
        api.application.short_product_name = "fclab"
        api.application.product = "Forti Containerlab"

        help_text = DockerfilePlugin().help(api)

        self.assertIn("Node YAML env fields", help_text)
        self.assertIn("FCLAB_DOCKERFILE", help_text)
        self.assertIn(
            "Runtime environment:\n"
            "    FCLAB_DOCKER_BUILD_JOBS  Concurrent image builds (default: 2)",
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
                    ("deploy", "-t", str(topology)),
                    ("deploy", "-t", str(topology)),
                    CallMode.NORMAL,
                ),
                api,
            )

        requests = build_images.call_args.args[0]
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].image, "eclab.containers/host-connector:latest")


if __name__ == "__main__":
    unittest.main()
