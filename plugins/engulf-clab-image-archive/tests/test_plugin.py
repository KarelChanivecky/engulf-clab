from __future__ import annotations

import tomllib
import unittest
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from engulf_api import ApplicationMetadata
from engulf_clab_lab_parser import TopologySession, load_topology
from engulf_docker_image_api import (
    DockerArchiveRecipe,
    ImageBuildGraph,
    ImageRequirement,
    RegisteredImageProvider,
)
from engulf_docker_image_core import provision_image_graph
from engulf_executable_wrapper_api import (
    AfterCallEvent,
    BeforeCallEvent,
    CallMode,
    PreparationFailedEvent,
    PreparedCallEvent,
)

from engulf_clab_image_archive.errors import ImageArchiveError
from engulf_clab_image_archive.plugin import PLUGIN_SCHEMA, ImageArchivePlugin
from engulf_clab_image_archive.provider import ARCHIVE_PROVIDER_ID

APPLICATION = ApplicationMetadata(
    application_id="engulf-clab",
    display_name="eclab",
    vendor="ECLAB",
    product="Engulf Containerlab",
    short_product_name="eclab",
    version="1.0.0",
)


def _lab(root: Path, *, archive: str, extra: str = "") -> Path:
    topology = root / "lab.clab.yml"
    topology.write_text(
        "topology:\n"
        "  nodes:\n"
        "    router:\n"
        "      image: example/router:1.0.0\n"
        "      env:\n"
        f"        ECLAB_IMAGE_ARCHIVE: {archive}\n" + extra,
        encoding="utf-8",
    )
    return topology


class SchemaTest(unittest.TestCase):
    def test_dependencies_are_declared_in_package_metadata(self) -> None:
        project_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
        project = tomllib.loads(project_path.read_text(encoding="utf-8"))["project"]
        group = project["entry-points"][
            "engulf.plugins.v1.dependency.engulf_clab_image_archive"
        ]

        self.assertEqual(
            group,
            {
                "engulf_clab.lab_parser": "preprocess=before; postprocess=none",
                "engulf_clab.image_build": "preprocess=after; postprocess=none",
                "engulf_clab.schema": "preprocess=after; postprocess=none",
            },
        )
        self.assertNotIn("plugin_dependencies", ImageArchivePlugin.__dict__)

    def test_schema_declares_every_node_variable(self) -> None:
        options = {option.name: option for option in PLUGIN_SCHEMA.options(APPLICATION)}

        self.assertEqual(options["ECLAB_IMAGE_ARCHIVE"].values, ("file-path",))
        self.assertEqual(options["ECLAB_IMAGE_ARCHIVE_REF"].values, ("image-reference",))
        self.assertEqual(options["ECLAB_IMAGE_ARCHIVE_RELOAD"].values, ("boolean",))

    def test_schema_documents_the_retag_rule(self) -> None:
        annotations = {
            annotation.subject: annotation for annotation in PLUGIN_SCHEMA.annotations(APPLICATION)
        }

        self.assertTrue(
            any(
                "retagged" in implication
                for implication in annotations["ECLAB_IMAGE_ARCHIVE"].implies
            )
        )
        self.assertEqual(annotations["ECLAB_IMAGE_ARCHIVE_REF"].requires, ("ECLAB_IMAGE_ARCHIVE",))


class HelpTest(unittest.TestCase):
    def test_help_uses_fixed_prefix_regardless_of_edition(self) -> None:
        api = Mock()
        api.application.short_product_name = "vendor clab"
        api.application.product = "Vendor Containerlab"

        help_text = ImageArchivePlugin().help(api)

        self.assertIn("Node YAML env fields", help_text)
        self.assertIn("ECLAB_IMAGE_ARCHIVE", help_text)
        self.assertIn("ECLAB_IMAGE_ARCHIVE_REF", help_text)
        self.assertIn("ECLAB_IMAGE_ARCHIVE_RELOAD", help_text)
        self.assertNotIn("FCLAB_IMAGE_ARCHIVE", help_text)


class RegistrationTest(unittest.TestCase):
    def test_before_goal_registers_the_provider_once(self) -> None:
        api = Mock()
        api.get_context.side_effect = lambda name, *default: (
            () if name == "org.engulf.docker-image.providers" else None
        )

        self.assertIsNone(ImageArchivePlugin().before_goal(Mock(), api))

        context_id, providers = api.set_context.call_args.args
        self.assertEqual(context_id, "org.engulf.docker-image.providers")
        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0].provider_id, ARCHIVE_PROVIDER_ID)


class LifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name).resolve()
        self.archive = self.root / "router.tar.gz"
        self.archive.write_bytes(b"archive")

    def _api(self, topology: Path) -> Mock:
        api = Mock()
        api.application.short_product_name = "eclab"
        api.application.product = "Engulf Containerlab"
        api.require_context.return_value = TopologySession(topology, load_topology(topology))
        return api

    def _prepare(self, plugin: ImageArchivePlugin, topology: Path) -> None:
        plugin.prepare_call(
            PreparedCallEvent(
                "containerlab",
                ("deploy", "--topo", str(topology)),
                ("deploy", "--topo", str(topology)),
                CallMode.NORMAL,
            ),
            self._api(topology),
        )

    def test_prepare_records_the_request_for_the_dispatcher(self) -> None:
        topology = _lab(self.root, archive="router.tar.gz")
        plugin = ImageArchivePlugin()

        self._prepare(plugin, topology)

        response = plugin._provider.provide(ImageRequirement("example/router:1.0.0"))
        assert response is not None and response.provision is not None
        recipe = response.provision.recipe
        assert isinstance(recipe, DockerArchiveRecipe)
        self.assertEqual(recipe.archive, self.archive)

    def test_prepare_expands_topology_environment_in_the_archive_path(self) -> None:
        topology = _lab(self.root, archive="${ROUTER_ARCHIVE}")
        plugin = ImageArchivePlugin()
        api = self._api(topology)
        api.require_context.return_value = TopologySession(
            topology, load_topology(topology, {"ROUTER_ARCHIVE": str(self.archive)})
        )

        plugin.prepare_call(
            PreparedCallEvent(
                "containerlab",
                ("deploy", "--topo", str(topology)),
                ("deploy", "--topo", str(topology)),
                CallMode.NORMAL,
            ),
            api,
        )

        response = plugin._provider.provide(ImageRequirement("example/router:1.0.0"))
        assert response is not None and response.provision is not None
        recipe = response.provision.recipe
        assert isinstance(recipe, DockerArchiveRecipe)
        self.assertEqual(recipe.archive, self.archive)

    def test_prepare_ignores_non_deploy_commands(self) -> None:
        topology = _lab(self.root, archive="router.tar.gz")
        plugin = ImageArchivePlugin()
        api = self._api(topology)

        plugin.prepare_call(
            PreparedCallEvent("containerlab", ("destroy",), ("destroy",), CallMode.NORMAL),
            api,
        )

        api.require_context.assert_not_called()
        self.assertIsNone(plugin._provider.provide(ImageRequirement("example/router:1.0.0")))

    def test_prepare_failure_in_later_plugin_clears_requests(self) -> None:
        topology = _lab(self.root, archive="router.tar.gz")
        plugin = ImageArchivePlugin()
        self._prepare(plugin, topology)

        plugin.prepare_failed(Mock(spec=PreparationFailedEvent), Mock())

        self.assertIsNone(plugin._provider.provide(ImageRequirement("example/router:1.0.0")))

    def test_after_call_clears_requests(self) -> None:
        topology = _lab(self.root, archive="router.tar.gz")
        plugin = ImageArchivePlugin()
        self._prepare(plugin, topology)

        plugin.after_call(Mock(spec=AfterCallEvent), Mock())

        self.assertIsNone(plugin._provider.provide(ImageRequirement("example/router:1.0.0")))

    def test_own_prepare_failure_clears_previous_requests(self) -> None:
        topology = _lab(self.root, archive="router.tar.gz")
        plugin = ImageArchivePlugin()
        self._prepare(plugin, topology)
        api = self._api(topology)
        api.require_context.return_value = object()

        with self.assertRaisesRegex(ImageArchiveError, "invalid shared topology session"):
            plugin.prepare_call(
                PreparedCallEvent("containerlab", ("deploy",), ("deploy",), CallMode.NORMAL),
                api,
            )

        self.assertIsNone(plugin._provider.provide(ImageRequirement("example/router:1.0.0")))

    def test_analyze_accepts_a_valid_declaration(self) -> None:
        topology = _lab(self.root, archive="router.tar.gz")
        api = Mock()

        contribution = ImageArchivePlugin().analyze_call(
            BeforeCallEvent(
                "containerlab",
                ("deploy", "--topo", str(topology)),
                CallMode.NORMAL,
                {},
            ),
            api,
        )

        self.assertIsNone(contribution)

    def test_analyze_preempts_a_missing_archive(self) -> None:
        topology = _lab(self.root, archive="absent.tar.gz")
        api = Mock()

        contribution = ImageArchivePlugin().analyze_call(
            BeforeCallEvent(
                "containerlab",
                ("deploy", "--topo", str(topology)),
                CallMode.NORMAL,
                {},
            ),
            api,
        )

        assert contribution is not None
        self.assertEqual(contribution.preempt_exit_code, 1)
        api.logger.error.assert_called_once()

    def test_analyze_ignores_help(self) -> None:
        topology = _lab(self.root, archive="absent.tar.gz")

        self.assertIsNone(
            ImageArchivePlugin().analyze_call(
                BeforeCallEvent(
                    "containerlab",
                    ("deploy", "--topo", str(topology)),
                    CallMode.HELP,
                    {},
                ),
                Mock(),
            )
        )


class DispatcherIntegrationTest(unittest.TestCase):
    """Resolve a topology through the real dispatcher with Docker stubbed out."""

    def setUp(self) -> None:
        self._directory = TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name).resolve()
        (self.root / "router.tar.gz").write_bytes(b"archive")

    def test_archive_recipe_wins_over_the_pull_fallback(self) -> None:
        topology = _lab(self.root, archive="router.tar.gz")
        plugin = ImageArchivePlugin()
        api = Mock()
        api.application.short_product_name = "eclab"
        api.require_context.return_value = TopologySession(topology, load_topology(topology))
        api.leases.return_value = nullcontext()

        plugin.prepare_call(
            PreparedCallEvent(
                "containerlab",
                ("deploy", "--topo", str(topology)),
                ("deploy", "--topo", str(topology)),
                CallMode.NORMAL,
            ),
            api,
        )

        commands: list[tuple[str, ...]] = []

        def run(command: object, **kwargs: object) -> Mock:
            argv = tuple(command)  # type: ignore[call-overload]
            commands.append(argv)
            result = Mock()
            result.returncode = 0
            result.stdout = (
                "Loaded image: example/router:1.0.0\n" if argv[:2] == ("docker", "load") else ""
            )
            return result

        with (
            patch("engulf_docker_image_core.build.shutil.which", return_value="/usr/bin/docker"),
            patch("engulf_docker_image_core.build.subprocess.run", side_effect=run),
        ):
            outcome = provision_image_graph(
                ImageBuildGraph((ImageRequirement("example/router:1.0.0"),)),
                api=api,
                providers=(
                    RegisteredImageProvider(ARCHIVE_PROVIDER_ID, plugin._provider, 72),
                ),
            )

        self.assertEqual(outcome.loaded, ("example/router:1.0.0",))
        self.assertEqual(outcome.pulled, ())
        self.assertNotIn(("docker", "pull", "example/router:1.0.0"), commands)
