from __future__ import annotations

import unittest
from pathlib import Path

from engulf_clab_containers_api import (
    ContainerBuildRecipe,
    ContainerCollectionPlugin,
    ContainerDefinition,
    ContainerNodeRequirements,
    image_namespace,
)


class ContractTest(unittest.TestCase):
    def test_definition_is_immutable_and_namespace_is_derived(self) -> None:
        node = ContainerNodeRequirements(cap_add=("NET_ADMIN",), sysctls={"net.ipv4.ip_forward": 1})
        definition = ContainerDefinition(
            "host-connector",
            "Connect lab VIPs",
            ContainerBuildRecipe(Path("/tmp/Dockerfile"), Path("/tmp")),
            node,
        )
        self.assertEqual(image_namespace("engulf_clab.containers"), "engulf-clab.containers")
        self.assertEqual(definition.node.sysctls["net.ipv4.ip_forward"], 1)
        with self.assertRaises(TypeError):
            definition.node.sysctls["x"] = 1  # type: ignore[index]

    def test_rejects_unsafe_name(self) -> None:
        with self.assertRaises(ValueError):
            ContainerDefinition(
                "Host Connector",
                "bad",
                ContainerBuildRecipe(Path("/tmp/Dockerfile"), Path("/tmp")),
            )

    def test_collection_requires_a_qualified_plugin_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "dot-qualified"):
            ContainerCollectionPlugin("containers", ())


if __name__ == "__main__":
    unittest.main()
