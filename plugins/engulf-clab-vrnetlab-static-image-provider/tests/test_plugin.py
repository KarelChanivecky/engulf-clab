from __future__ import annotations

import tomllib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from engulf_api import InvocationAPI, RegistrationAPI
from engulf_clab_lab_parser import TOPOLOGY_CONTEXT, TopologySession
from engulf_clab_vrnetlab_build_api import VRNETLAB_BUILD_CONTEXT, VrnetlabBuildContext
from engulf_executable_wrapper_api import (
    ArgumentRegistry,
    BeforeCallEvent,
    CallMode,
    CompletionContext,
    PreparedCallEvent,
    Shell,
)

from engulf_clab_vrnetlab_static_image_provider.config import load_topology
from engulf_clab_vrnetlab_static_image_provider.errors import VrnetlabError
from engulf_clab_vrnetlab_static_image_provider.options import IMAGE_OPTION
from engulf_clab_vrnetlab_static_image_provider.plugin import VrnetlabPlugin


class StaticImageProviderPluginTest(unittest.TestCase):
    @staticmethod
    def api() -> Mock:
        api = Mock(spec=InvocationAPI)
        api.application.display_name = "engulf-clab"
        api.application.product = "Engulf Containerlab"
        api.application.short_product_name = "eclab"
        return api

    def test_dependencies_and_identity_are_declared_in_package_metadata(self) -> None:
        project_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
        project = tomllib.loads(project_path.read_text(encoding="utf-8"))["project"]
        entry_points = project["entry-points"]

        self.assertEqual(
            entry_points[
                "engulf.plugins.v1.dependency.engulf_clab_vrnetlab_static_image_provider"
            ],
            {
                "engulf_clab.lab_parser": "preprocess=before; postprocess=none",
                "engulf_clab.vrnetlab_build": "preprocess=after; postprocess=none",
                "engulf_clab.schema": "preprocess=after; postprocess=none",
            },
        )
        self.assertNotIn("plugin_dependencies", VrnetlabPlugin.__dict__)
        self.assertEqual(
            entry_points["engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper"],
            {
                "engulf_clab.vrnetlab_static_image_provider": (
                    "engulf_clab_vrnetlab_static_image_provider:plugin"
                )
            },
        )
        self.assertEqual(
            entry_points["engulf.plugins.v1.application.engulf_clab"],
            {
                "engulf_clab.vrnetlab_static_image_provider": (
                    "engulf_clab_vrnetlab_static_image_provider:plugin"
                )
            },
        )

    def test_help_lists_source_syntax_and_provider_role(self) -> None:
        help_text = VrnetlabPlugin().help(self.api())

        self.assertIn("Node YAML fields:", help_text)
        self.assertIn("ECLAB_VRNETLAB_TYPE", help_text)
        self.assertIn("--eclab-vrnetlab-image NODE=FILE", help_text)
        self.assertIn("--eclab-vrnetlab-build-jobs COUNT", help_text)
        self.assertIn("shared vrnetlab builder", help_text)
        self.assertIn("ECLAB_VRNETLAB_IMG_PATH", help_text)
        self.assertIn("ECLAB_VM_IMG", help_text)
        self.assertIn("ECLAB_VM_SRC", help_text)

    def test_registers_repeatable_node_image_option(self) -> None:
        registry = ArgumentRegistry()

        VrnetlabPlugin().register_arguments(registry, Mock(spec=RegistrationAPI))

        option = registry.find_exact(IMAGE_OPTION)
        self.assertIsNotNone(option)
        assert option is not None
        self.assertTrue(option.repeatable)
        self.assertFalse(option.suggest_assignment)
        self.assertEqual(option.metavar, "NODE=FILE")
        self.assertIsNotNone(option.value_completer)
        self.assertIsNotNone(option.when)
        assert option.when is not None
        self.assertTrue(
            option.when(
                CompletionContext(
                    Shell.BASH,
                    "eclab",
                    "containerlab",
                    ("deploy", "--"),
                    1,
                )
            )
        )

    def test_help_and_non_deploy_calls_do_nothing(self) -> None:
        api = self.api()
        plugin = VrnetlabPlugin()

        plugin.analyze_call(
            BeforeCallEvent("containerlab", ("deploy",), CallMode.HELP),
            api,
        )
        plugin.analyze_call(
            BeforeCallEvent("containerlab", ("destroy",), CallMode.NORMAL),
            api,
        )

        api.get_context.assert_not_called()
        api.state.assert_not_called()

    def test_invalid_yaml_is_reported_as_provider_error(self) -> None:
        with TemporaryDirectory() as directory:
            topology = Path(directory) / "lab.clab.yml"
            topology.write_text("topology: [\n", encoding="utf-8")
            with self.assertRaises(VrnetlabError):
                load_topology(topology)

    def test_analyze_removes_all_image_selector_arguments(self) -> None:
        with TemporaryDirectory() as directory:
            topology = Path(directory) / "lab.clab.yml"
            topology.write_text(
                """
name: router-lab
topology:
  nodes:
    r1:
      image: vrnetlab/vendor_router:1
      env:
        ECLAB_VRNETLAB_TYPE: vendor/router
""",
                encoding="utf-8",
            )
            contribution = VrnetlabPlugin().analyze_call(
                BeforeCallEvent(
                    "containerlab",
                    (
                        "deploy",
                        "-t",
                        str(topology),
                        IMAGE_OPTION,
                        "r1=/images/r1.qcow2",
                        f"{IMAGE_OPTION}=default=/images/default.qcow2",
                    ),
                    CallMode.NORMAL,
                ),
                self.api(),
            )

        self.assertIsNotNone(contribution)
        assert contribution is not None
        self.assertEqual(contribution.removals, frozenset({3, 4, 5}))
        self.assertIsNone(contribution.preempt_exit_code)

    def test_prepare_publishes_resolved_paths_and_job_limit(self) -> None:
        with TemporaryDirectory() as directory:
            topology = Path(directory) / "lab.clab.yml"
            topology.write_text(
                """
name: router-lab
topology:
  nodes:
    r1:
      image: vrnetlab/vendor_router:1
      env:
        ECLAB_VRNETLAB_TYPE: vendor/router
""",
                encoding="utf-8",
            )
            api = self.api()
            contexts: dict[str, object] = {}
            api.get_context.side_effect = lambda key, default=None: contexts.get(key, default)
            api.set_context.side_effect = lambda key, value: contexts.__setitem__(key, value)
            api.require_context.return_value = TopologySession(
                topology,
                load_topology(topology),
            )

            VrnetlabPlugin().prepare_call(
                PreparedCallEvent(
                    "containerlab",
                    ("deploy", IMAGE_OPTION, "r1=/images/r1.qcow2"),
                    ("deploy",),
                    CallMode.NORMAL,
                ),
                api,
            )

        self.assertIsInstance(contexts[VRNETLAB_BUILD_CONTEXT], VrnetlabBuildContext)
        build_context = contexts[VRNETLAB_BUILD_CONTEXT]
        assert isinstance(build_context, VrnetlabBuildContext)
        self.assertEqual(build_context.sources(), {"default": Path("/images/r1.qcow2")})
        self.assertEqual(build_context.max_workers, 2)
        api.require_context.assert_called_once_with(TOPOLOGY_CONTEXT)


if __name__ == "__main__":
    unittest.main()
