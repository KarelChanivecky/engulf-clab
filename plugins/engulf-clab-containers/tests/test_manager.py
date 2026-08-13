from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from engulf_clab_containers_api import (
    ContainerBuildRecipe,
    ContainerDefinition,
    ContainerNodeRequirements,
    RegisteredContainerCollection,
)

from engulf_clab_containers.errors import ContainersError
from engulf_clab_containers.manager import catalog, matching_container, topology_edits


class ManagerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        context = Path(self.temporary.name)
        (context / "Dockerfile").write_text("FROM scratch\n")
        definition = ContainerDefinition(
            "host-connector",
            "Connect hosts",
            ContainerBuildRecipe(context / "Dockerfile", context),
            ContainerNodeRequirements(cap_add=("NET_ADMIN",), sysctls={"net.ipv4.ip_forward": 1}),
        )
        self.containers = catalog(
            (RegisteredContainerCollection("eclab.containers", (definition,)),)
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_untagged_image_is_canonicalized_and_fields_merged(self) -> None:
        document = {
            "topology": {
                "nodes": {
                    "plug": {
                        "image": "eclab.containers/host-connector",
                        "cap-add": ["SYS_PTRACE"],
                        "env": {"ECLAB_CONNECT_HOST": "10.0.0.1;192.0.2.1"},
                    }
                }
            }
        }
        edits = topology_edits(document, self.containers, prefix="FCLAB")
        fields = edits[0][1]
        self.assertEqual(fields["image"], "eclab.containers/host-connector:latest")
        self.assertEqual(fields["cap-add"], ["SYS_PTRACE", "NET_ADMIN"])
        self.assertIn("FCLAB_DOCKERFILE", fields["env"])

    def test_non_latest_tag_and_network_mode_are_rejected(self) -> None:
        with self.assertRaisesRegex(ContainersError, "only supports tag latest"):
            matching_container("eclab.containers/host-connector:dev", self.containers)
        document = {
            "topology": {
                "nodes": {
                    "plug": {
                        "image": "eclab.containers/host-connector",
                        "network-mode": "none",
                    }
                }
            }
        }
        with self.assertRaisesRegex(ContainersError, "eth0"):
            topology_edits(document, self.containers, prefix="ECLAB")

    def test_unknown_name_in_owned_namespace_is_rejected(self) -> None:
        with self.assertRaisesRegex(ContainersError, "has no container"):
            matching_container("eclab.containers/not-installed", self.containers)


if __name__ == "__main__":
    unittest.main()
