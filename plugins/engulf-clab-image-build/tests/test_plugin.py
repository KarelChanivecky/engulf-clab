from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from engulf_api import ApplicationMetadata
from engulf_clab_dockerfile_build.plugin import DockerfilePlugin
from engulf_clab_lab_parser import TopologySession, load_topology
from engulf_docker_image_api import IMAGE_GRAPH_CONTEXT
from engulf_docker_image_core import DockerImageError
from engulf_executable_wrapper_api import ArgumentRegistry, CallMode, PreparedCallEvent

from engulf_clab_image_build.plugin import PLUGIN_SCHEMA, ImageBuildPlugin, image_build_jobs

_APPLICATION = ApplicationMetadata(
    application_id="engulf-clab",
    display_name="eclab",
    vendor="ECLAB",
    product="Engulf Containerlab",
    short_product_name="eclab",
    version="1.0.0",
)


class ImageBuildPluginTest(unittest.TestCase):
    def test_help_lists_plain_containerlab_env_controls(self) -> None:
        text = ImageBuildPlugin().help(Mock())
        self.assertIn("ECLAB_IMAGE_PARAM_name", text)
        self.assertIn("--eclab-image-build-jobs", text)

    def test_legacy_jobs_environment_remains_supported(self) -> None:
        self.assertEqual(image_build_jobs({"ECLAB_DOCKER_BUILD_JOBS": "7"}), 7)
        self.assertEqual(
            image_build_jobs({"ECLAB_DOCKER_BUILD_JOBS": "7", "ECLAB_IMAGE_BUILD_JOBS": "3"}),
            3,
        )

    def test_registers_job_flags_as_one_environment_bound_option(self) -> None:
        registry = ArgumentRegistry()

        ImageBuildPlugin().register_arguments(registry, Mock())

        self.assertEqual(len(registry.options), 1)
        option = registry.options[0]
        self.assertEqual(
            option.names,
            ("--eclab-image-build-jobs", "--eclab-docker-build-jobs"),
        )
        self.assertTrue(option.takes_value)
        self.assertEqual(option.environment, "ECLAB_IMAGE_BUILD_JOBS")

    def test_schema_exposes_recursive_build_behavior_without_opening_reference(self) -> None:
        options = {option.name: option for option in PLUGIN_SCHEMA.options(_APPLICATION)}
        annotations = {
            annotation.subject: annotation for annotation in PLUGIN_SCHEMA.annotations(_APPLICATION)
        }

        self.assertIn("recursive provider build graph", options["image"].explanation)
        self.assertEqual(
            {name for name in options if name.startswith("ECLAB_IMAGE_") and name.endswith("*")},
            {"ECLAB_IMAGE_PARAM_*"},
        )
        implications = annotations["image"].implies
        self.assertTrue(any("literal Dockerfile FROM base" in item for item in implications))
        self.assertTrue(any("dependency-first" in item for item in implications))
        self.assertTrue(any("dynamic FROM" in item for item in implications))

    @patch("engulf_clab_image_build.plugin.provision_image_graph")
    def test_materialized_node_images_become_roots_and_disable_later_pulls(
        self, provision: Mock
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            topology = Path(directory) / "lab.clab.yml"
            topology.write_text(
                "topology:\n  nodes:\n    app:\n      image: example/app\n"
                "      env:\n        ECLAB_IMAGE_PARAM_RELEASE: '42'\n",
                encoding="utf-8",
            )
            session = TopologySession(topology, load_topology(topology))
            api = Mock()
            api.require_context.return_value = session
            api.get_context.return_value = ()
            ImageBuildPlugin().prepare_call(
                PreparedCallEvent("containerlab", ("deploy",), ("deploy",), CallMode.NORMAL),
                api,
            )

            materialized = session.materialize()

        graph = provision.call_args.args[0]
        self.assertEqual(graph.roots[0].reference, "example/app")
        self.assertEqual(graph.roots[0].parameters[0].name, "RELEASE")
        self.assertEqual(
            materialized["topology"]["nodes"]["app"]["image-pull-policy"],
            "Never",
        )

    def test_dynamic_node_image_is_rejected_instead_of_delegated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            topology = Path(directory) / "lab.clab.yml"
            topology.write_text(
                "topology:\n  nodes:\n    app:\n      image: ${APP_IMAGE}\n",
                encoding="utf-8",
            )
            session = TopologySession(topology, load_topology(topology))
            api = Mock()
            api.require_context.return_value = session
            api.get_context.return_value = ()

            with self.assertRaisesRegex(DockerImageError, "did not resolve to a literal"):
                ImageBuildPlugin().prepare_call(
                    PreparedCallEvent("containerlab", ("deploy",), ("deploy",), CallMode.NORMAL),
                    api,
                )

    @patch("engulf_clab_image_build.plugin.provision_image_graph")
    def test_containerlab_defaulted_image_is_expanded_before_provisioning(
        self, provision: Mock
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            topology = Path(directory) / "lab.clab.yml"
            topology.write_text(
                "topology:\n"
                "  nodes:\n"
                "    fgt:\n"
                "      image: ${FGT_IMAGE:=fgt:8.0.1.0203}\n",
                encoding="utf-8",
            )
            session = TopologySession(topology, load_topology(topology, {}))
            api = Mock()
            api.require_context.return_value = session
            api.get_context.return_value = ()

            ImageBuildPlugin().prepare_call(
                PreparedCallEvent("containerlab", ("deploy",), ("deploy",), CallMode.NORMAL),
                api,
            )

        graph = provision.call_args.args[0]
        self.assertEqual(graph.roots[0].reference, "fgt:8.0.1.0203")

    @patch("engulf_clab_image_build.plugin.provision_image_graph")
    def test_build_only_dockerfile_node_is_a_root_but_not_a_runtime_node(
        self, provision: Mock
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            topology = root / "lab.clab.yml"
            dockerfile = root / "Dockerfile"
            dockerfile.write_text("FROM scratch\n", encoding="utf-8")
            topology.write_text(
                "topology:\n"
                "  nodes:\n"
                "    base-build:\n"
                "      image: example/base:latest\n"
                "      env:\n"
                "        ECLAB_DOCKERFILE: Dockerfile\n"
                "        ECLAB_DOCKER_CTX: .\n"
                '        ECLAB_DOCKER_BASE_NODE: "true"\n'
                "    app:\n"
                "      image: example/app:latest\n",
                encoding="utf-8",
            )
            session = TopologySession(topology, load_topology(topology))
            contexts: dict[str, object] = {IMAGE_GRAPH_CONTEXT: ()}
            api = Mock()
            api.require_context.side_effect = lambda key: (
                session if key == "engulf_clab.topology.session" else contexts[key]
            )
            api.get_context.side_effect = lambda key, default=None: contexts.get(key, default)
            api.set_context.side_effect = lambda key, value: contexts.__setitem__(key, value)
            event = PreparedCallEvent(
                "containerlab",
                ("deploy",),
                ("deploy",),
                CallMode.NORMAL,
            )

            DockerfilePlugin().prepare_call(event, api)
            ImageBuildPlugin().prepare_call(event, api)

            materialized = session.materialize()

        graph = provision.call_args.args[0]
        self.assertEqual(
            tuple(root.reference for root in graph.roots),
            ("example/base:latest", "example/app:latest"),
        )
        self.assertNotIn("base-build", materialized["topology"]["nodes"])
        self.assertEqual(
            materialized["topology"]["nodes"]["app"]["image-pull-policy"],
            "Never",
        )


if __name__ == "__main__":
    unittest.main()
