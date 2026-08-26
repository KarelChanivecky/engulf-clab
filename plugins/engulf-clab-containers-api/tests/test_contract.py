from __future__ import annotations

import unittest
from pathlib import Path

from engulf_docker_image_api import ImageParameter, ImageRequirement

from engulf_clab_containers_api import (
    ContainerBuildRecipe,
    ContainerCollectionPlugin,
    ContainerDefinition,
    ContainerImageProvider,
    ContainerNodeRequirements,
    RegisteredContainerCollection,
    image_namespace,
)


class ContractTest(unittest.TestCase):
    def test_definition_is_immutable_and_namespace_is_derived(self) -> None:
        node = ContainerNodeRequirements(cap_add=("NET_ADMIN",), sysctls={"net.ipv4.ip_forward": 1})
        definition = ContainerDefinition(
            "host-connector",
            "Connect lab VIPs",
            ContainerBuildRecipe(
                Path("/tmp/Dockerfile"),
                Path("/tmp"),
                build_args={"EDITION": "community"},
                parameter_build_args={"RELEASE": "APP_RELEASE"},
            ),
            node,
        )
        self.assertEqual(image_namespace("engulf_clab.containers"), "engulf-clab.containers")
        self.assertEqual(definition.node.sysctls["net.ipv4.ip_forward"], 1)
        self.assertEqual(definition.build.parameter_build_args["RELEASE"], "APP_RELEASE")
        with self.assertRaises(TypeError):
            definition.node.sysctls["x"] = 1  # type: ignore[index]
        with self.assertRaises(TypeError):
            definition.build.build_args["EDITION"] = "enterprise"  # type: ignore[index]
        provider = ContainerImageProvider(
            (RegisteredContainerCollection("org.example.containers", (definition,)),)
        )
        response = provider.provide(
            ImageRequirement(
                "org.example.containers/host-connector",
                (ImageParameter("RELEASE", "42"),),
            )
        )
        assert response is not None and response.provision is not None
        self.assertIn(("APP_RELEASE", "42"), response.provision.recipe.build_args)

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
