from __future__ import annotations

import unittest

from engulf_clab_containers_api import ContainerCollectionPlugin, ContainerDefinition

from engulf_clab_containers_core import (
    HOST_CONNECTOR,
    LDAP_389DS,
    PROXY_NODE,
    UBUNTU_FIREFOX_GUI,
    plugin,
)


class CollectionTest(unittest.TestCase):
    def test_plugin_identity_and_container_names(self) -> None:
        self.assertIsInstance(plugin, ContainerCollectionPlugin)
        self.assertEqual(plugin.plugin_id, "eclab.containers")
        self.assertEqual(
            tuple(item.name for item in plugin.containers),
            ("host-connector", "ldap-389ds", "proxy-node", "ubuntu-firefox-gui"),
        )

    def test_exported_definitions_are_registered_once(self) -> None:
        self.assertEqual(
            plugin.containers,
            (HOST_CONNECTOR, LDAP_389DS, PROXY_NODE, UBUNTU_FIREFOX_GUI),
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

    def test_default_ldap_seed_matches_default_suffix(self) -> None:
        seed = (
            LDAP_389DS.build.context / "containers" / "ldap-389ds" / "seed.ldif"
        ).read_text(encoding="utf-8")
        self.assertIn("dc=lab,dc=local", seed)
        self.assertNotIn("dc=ldap,dc=fortinet,dc=com", seed)


if __name__ == "__main__":
    unittest.main()
