from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from engulf_api import ApplicationMetadata
from engulf_clab_lab_parser import TopologySession, load_topology
from engulf_executable_wrapper_api import CallMode, PreparedCallEvent

from engulf_clab_dockerfile_build.plugin import PLUGIN_SCHEMA, DockerfilePlugin
from engulf_clab_dockerfile_build.topology import topology_path_from_args


class PluginHelpTest(unittest.TestCase):
    def test_schema_declares_base_node_removal_semantics(self) -> None:
        application = ApplicationMetadata(
            application_id="engulf-clab",
            display_name="eclab",
            vendor="ECLAB",
            product="Engulf Containerlab",
            short_product_name="eclab",
            version="1.0.0",
        )
        options = {option.name: option for option in PLUGIN_SCHEMA.options(application)}
        annotations = {
            annotation.subject: annotation
            for annotation in PLUGIN_SCHEMA.annotations(application)
        }

        self.assertEqual(options["ECLAB_DOCKER_BASE_NODE"].values, ("boolean",))
        self.assertTrue(
            any(
                "deleted from the derived topology" in implication
                for implication in annotations["ECLAB_DOCKER_BASE_NODE"].implies
            )
        )

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
        self.assertIn("ECLAB_DOCKER_BASE_NODE", help_text)
        self.assertNotIn("FCLAB_DOCKERFILE", help_text)
        self.assertIn("literal built tag; variables are unsupported", help_text)
        self.assertIn("image-build dispatcher owns concurrency", help_text)

    def test_prepare_contributes_materialized_topology_recipe(self) -> None:
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
            api.get_context.return_value = ()

            DockerfilePlugin().prepare_call(
                PreparedCallEvent(
                    "containerlab",
                    ("deploy",),
                    ("deploy",),
                    CallMode.NORMAL,
                ),
                api,
            )

        context_id, graphs = api.set_context.call_args.args
        self.assertEqual(context_id, "org.engulf.docker-image.graphs")
        self.assertEqual(len(graphs), 1)
        self.assertEqual(
            graphs[0].provisions[0].image,
            "eclab.containers/host-connector:latest",
        )

    def test_prepare_roots_base_node_then_removes_it_from_derived_topology(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            topology = root / "lab.clab.yml"
            dockerfile = root / "Dockerfile"
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
            dockerfile.write_text("FROM scratch\n", encoding="utf-8")
            session = TopologySession(topology, load_topology(topology))
            api = Mock()
            api.require_context.return_value = session
            api.get_context.return_value = ()

            DockerfilePlugin().prepare_call(
                PreparedCallEvent(
                    "containerlab",
                    ("deploy",),
                    ("deploy",),
                    CallMode.NORMAL,
                ),
                api,
            )

            _, graphs = api.set_context.call_args.args
            materialized = session.materialize()

        self.assertEqual(
            tuple(root.reference for root in graphs[0].roots),
            ("example/base:latest",),
        )
        self.assertEqual(
            tuple(provision.image for provision in graphs[0].provisions),
            ("example/base:latest",),
        )
        self.assertNotIn("base-build", materialized["topology"]["nodes"])
        self.assertIn("app", materialized["topology"]["nodes"])


if __name__ == "__main__":
    unittest.main()
