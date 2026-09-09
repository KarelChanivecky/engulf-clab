from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

from engulf_api import ApplicationMetadata
from engulf_clab_containers_api import ContainerCollectionPlugin, ContainerDefinition
from engulf_clab_pki_linux_core import image_plugin as runtime_image_plugin
from engulf_clab_pki_linux_debian import image_plugin as debian_image_plugin
from engulf_clab_pki_linux_fedora import image_plugin as fedora_image_plugin
from engulf_clab_schema_api import ExplainedValue, ValueMode, ValueType
from engulf_docker_image_api import (
    DockerImagePlugin,
    ImageBuildGraph,
    ImageRequirement,
    RegisteredImageProvider,
)
from engulf_docker_image_core import resolve_image_graph

from engulf_clab_containers_pki import DEBIAN, FEDORA, image_plugin, plugin
from engulf_clab_containers_pki.plugin import PLUGIN_SCHEMA, PkiContainerCollectionPlugin

APPLICATION = ApplicationMetadata(
    application_id="engulf-clab",
    display_name="ECLAB",
    vendor="Engulf",
    product="ECLAB",
    short_product_name="eclab",
    version="1.0",
)


class PkiContainerCollectionTest(unittest.TestCase):
    def test_adapters_have_distinct_goal_specific_identities(self) -> None:
        self.assertEqual(plugin.plugin_id, "eclab.containers.pki")
        self.assertEqual(image_plugin.plugin_id, "eclab.containers.pki.images")
        self.assertEqual(plugin.goal_requirement.goal_id, "org.engulf.executable-wrapper")
        self.assertEqual(image_plugin.goal_requirement.goal_id, "org.engulf.docker-image")

    def test_dependencies_are_declared_in_package_metadata(self) -> None:
        project_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
        project = tomllib.loads(project_path.read_text(encoding="utf-8"))["project"]
        entry_points = project["entry-points"]

        self.assertEqual(
            entry_points["engulf.plugins.v1.dependency.eclab_containers_pki"],
            {
                "engulf_clab.containers": "preprocess=after; postprocess=none",
                "engulf_clab.schema": "preprocess=after; postprocess=none",
            },
        )
        self.assertNotIn("plugin_dependencies", PkiContainerCollectionPlugin.__dict__)
        self.assertEqual(
            entry_points["engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper"],
            {"eclab.containers.pki": "engulf_clab_containers_pki:plugin"},
        )
        self.assertEqual(
            entry_points["engulf.plugins.v1.application.engulf_clab"],
            {"eclab.containers.pki": "engulf_clab_containers_pki:plugin"},
        )
        self.assertEqual(
            entry_points["engulf.plugins.v1.goal.v1.org_engulf_docker_image"],
            {"eclab.containers.pki.images": "engulf_clab_containers_pki:image_plugin"},
        )
        dependencies = tuple(project["dependencies"])
        self.assertIn("engulf-clab-pki>=0.3.1,<1", dependencies)
        self.assertIn("engulf-clab-pki-linux-debian>=0.1.2,<1", dependencies)
        self.assertIn("engulf-clab-pki-linux-fedora>=0.1.2,<1", dependencies)

    def test_collection_registers_both_pki_bases(self) -> None:
        self.assertIsInstance(plugin, ContainerCollectionPlugin)
        self.assertEqual(plugin.containers, (DEBIAN, FEDORA))
        self.assertEqual(tuple(item.name for item in plugin.containers), ("debian", "fedora"))

    def test_generic_goal_adapter_provides_both_recipes(self) -> None:
        self.assertIsInstance(image_plugin, DockerImagePlugin)
        for name in ("debian", "fedora"):
            image = f"eclab.containers.pki/{name}"
            with self.subTest(image=image):
                response = image_plugin.provider.provide(ImageRequirement(image))
                assert response is not None and response.provision is not None
                self.assertEqual(response.provision.image, f"{image}:latest")

    def test_recipes_are_typed_and_inside_the_package_context(self) -> None:
        for definition in plugin.containers:
            with self.subTest(definition=definition.name):
                self.assertIsInstance(definition, ContainerDefinition)
                self.assertEqual(definition.node.kind, "linux")
                self.assertTrue(definition.node.requires_management)
                self.assertTrue(definition.summary.strip())
                self.assertTrue(definition.build.dockerfile.is_file())
                self.assertTrue(definition.build.context.is_dir())
                self.assertTrue(
                    definition.build.dockerfile.is_relative_to(definition.build.context)
                )

    def test_bases_inherit_installers_and_preserve_runtime_entrypoint(self) -> None:
        cases = (
            (DEBIAN, "engulf-clab.pki-linux-debian/installer:latest"),
            (FEDORA, "engulf-clab.pki-linux-fedora/installer:latest"),
        )
        for definition, installer in cases:
            with self.subTest(definition=definition.name):
                source = definition.build.dockerfile.read_text(encoding="utf-8")
                self.assertIn(f"FROM {installer}\n", source)
                self.assertIn("RUN /opt/eclab-pki/install\n", source)
                self.assertIn(
                    'ENTRYPOINT ["/opt/eclab-pki/entrypoint", "--"]\n',
                    source,
                )
                self.assertIn('CMD ["sleep", "infinity"]\n', source)

    def test_resolver_builds_installer_and_runtime_before_each_base(self) -> None:
        providers = tuple(
            RegisteredImageProvider(item.plugin_id, item.provider)
            for item in (
                image_plugin,
                runtime_image_plugin,
                debian_image_plugin,
                fedora_image_plugin,
            )
        )
        cases = (
            (
                "eclab.containers.pki/debian",
                "engulf-clab.pki-linux-debian/installer:latest",
            ),
            (
                "eclab.containers.pki/fedora",
                "engulf-clab.pki-linux-fedora/installer:latest",
            ),
        )
        for base, installer in cases:
            with self.subTest(base=base):
                graph = resolve_image_graph(
                    ImageBuildGraph((ImageRequirement(base),)), providers
                )
                self.assertEqual(graph.image(base).dependencies, (installer,))
                self.assertIn(
                    "engulf-clab.pki-linux-core/runtime:latest",
                    graph.image(installer).dependencies,
                )

    def test_schema_advertises_images_and_packaged_guides(self) -> None:
        snapshot = PLUGIN_SCHEMA.snapshot(APPLICATION)
        image = next(option for option in snapshot.options if option.name == "image")

        self.assertIs(image.value_mode, ValueMode.TYPE)
        self.assertEqual(image.values, (ValueType.IMAGE_REFERENCE.value,))
        self.assertEqual(
            image.explained_values,
            (
                ExplainedValue(
                    "eclab.containers.pki/debian",
                    "Provide a Debian 13 base that applies projected eclab PKI trust at startup.",
                ),
                ExplainedValue(
                    "eclab.containers.pki/fedora",
                    "Provide a Fedora 44 base that applies projected eclab PKI trust at startup.",
                ),
            ),
        )
        paths = {reference.path for reference in snapshot.references}
        self.assertEqual(
            paths,
            {
                "USAGE.md",
                "containers/debian/USAGE.md",
                "containers/fedora/USAGE.md",
            },
        )
        routes = {route.task: route.reference for route in snapshot.routes}
        self.assertEqual(routes["build-pki-container"], "USAGE.md")


if __name__ == "__main__":
    unittest.main()
