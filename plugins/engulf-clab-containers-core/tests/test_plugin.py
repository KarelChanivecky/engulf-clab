from __future__ import annotations

import unittest

from engulf_api import ApplicationMetadata
from engulf_clab_containers_api import ContainerCollectionPlugin, ContainerDefinition
from engulf_clab_schema_api import ExplainedValue, ValueMode, ValueType

from engulf_clab_containers_core import HOST_CONNECTOR, WAN_ACCESS, plugin
from engulf_clab_containers_core.plugin import PLUGIN_SCHEMA

APPLICATION = ApplicationMetadata(
    application_id="engulf-clab",
    display_name="ECLAB",
    vendor="Engulf",
    product="ECLAB",
    short_product_name="eclab",
    version="1.0",
)


class CollectionTest(unittest.TestCase):
    def test_plugin_identity_and_container_names(self) -> None:
        self.assertIsInstance(plugin, ContainerCollectionPlugin)
        self.assertEqual(plugin.plugin_id, "eclab.containers")
        self.assertEqual(
            tuple(item.name for item in plugin.containers),
            ("host-connector", "wan-access"),
        )

    def test_exported_definitions_are_registered_once(self) -> None:
        self.assertEqual(
            plugin.containers,
            (HOST_CONNECTOR, WAN_ACCESS),
        )

    def test_recipes_are_typed_and_inside_the_package_context(self) -> None:
        for definition in plugin.containers:
            with self.subTest(definition=definition.name):
                self.assertIsInstance(definition, ContainerDefinition)
                self.assertEqual(definition.node.kind, "linux")
                self.assertTrue(definition.summary.strip())
                self.assertTrue(definition.build.dockerfile.is_file())
                self.assertTrue(definition.build.context.is_dir())
                self.assertTrue(
                    definition.build.dockerfile.is_relative_to(definition.build.context)
                )

    def test_dockerfile_copy_sources_exist(self) -> None:
        for definition in plugin.containers:
            dockerfile = definition.build.dockerfile
            for line in dockerfile.read_text(encoding="utf-8").splitlines():
                if not line.startswith("COPY "):
                    continue
                source = line.split()[1]
                self.assertTrue(
                    (definition.build.context / source).exists(),
                    f"{definition.name}: missing COPY source {source}",
                )

    def test_schema_advertises_images_and_packages_per_node_guides(self) -> None:
        snapshot = PLUGIN_SCHEMA.snapshot(APPLICATION)
        image = next(option for option in snapshot.options if option.name == "image")

        self.assertIs(image.value_mode, ValueMode.TYPE)
        self.assertEqual(image.values, (ValueType.IMAGE_REFERENCE.value,))
        self.assertEqual(
            image.explained_values,
            (
                ExplainedValue(
                    "eclab.containers/host-connector",
                    "Map lab-facing VIPs to external IPv4 or IPv6 hosts through management networking.",
                ),
                ExplainedValue(
                    "eclab.containers/wan-access",
                    "Provide outbound IPv4 NAT with optional DHCP on one lab-facing interface.",
                ),
            ),
        )
        annotations = {annotation.subject: annotation for annotation in snapshot.annotations}
        wan_image = ("node image selects eclab.containers/wan-access",)
        for variable in (
            "ECLAB_DHCP_SUBNET",
            "ECLAB_DHCP_GATEWAY",
            "ECLAB_DHCP_POOL_START",
            "ECLAB_DHCP_POOL_END",
            "ECLAB_DHCP_DNS",
            "ECLAB_DHCP_LEASE_TIME",
        ):
            self.assertEqual(annotations[variable].requires, wan_image)
        paths = {reference.path for reference in snapshot.references}
        self.assertIn("containers/host-connector/USAGE.md", paths)
        self.assertIn("containers/wan-access/USAGE.md", paths)
        routes = {route.task: route.reference for route in snapshot.routes}
        self.assertEqual(
            routes["connect-lab-to-host"], "containers/host-connector/USAGE.md"
        )
        self.assertEqual(
            routes["provide-lab-wan-access"], "containers/wan-access/USAGE.md"
        )

if __name__ == "__main__":
    unittest.main()
