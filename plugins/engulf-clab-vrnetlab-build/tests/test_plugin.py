from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from engulf_api import InvocationAPI, RegistrationAPI, StateScope
from engulf_clab_ensure_vrnetlab import ENSURE_VRNETLAB_PLUGIN_ID
from engulf_clab_lab_parser import TopologySession
from engulf_executable_wrapper_api import (
    ArgumentRegistry,
    BeforeCallEvent,
    CallMode,
    CompletionContext,
    PreparedCallEvent,
    Shell,
)

from engulf_clab_vrnetlab_build.errors import VrnetlabError
from engulf_clab_vrnetlab_build.options import IMAGE_OPTION
from engulf_clab_vrnetlab_build.plugin import VrnetlabPlugin
from engulf_clab_vrnetlab_build.topology import load_topology


class PluginLifecycleTest(unittest.TestCase):
    @staticmethod
    def api() -> Mock:
        api = Mock(spec=InvocationAPI)
        api.application.display_name = "engulf-clab"
        api.application.product = "Engulf Containerlab"
        api.application.short_product_name = "eclab"
        return api

    def test_ensure_vrnetlab_is_a_hard_preprocess_dependency(self) -> None:
        dependency = VrnetlabPlugin().plugin_dependencies[0]
        self.assertEqual(dependency.plugin_id, ENSURE_VRNETLAB_PLUGIN_ID)

    def test_help_identifies_node_environment_fields(self) -> None:
        help_text = VrnetlabPlugin().help(self.api())

        self.assertIn("Node YAML fields:", help_text)
        self.assertIn(
            "image                      Use a lab-unique requested Docker tag",
            help_text,
        )
        self.assertIn(
            "ECLAB_VRNETLAB_TYPE      Opt in and select the vrnetlab builder",
            help_text,
        )
        self.assertIn(
            "Wrapper options:\n"
            "    --eclab-vrnetlab-image NODE=FILE  Select a repeatable node image source",
            help_text,
        )
        self.assertIn("default=FILE", help_text)
        self.assertIn("ECLAB_VRNETLAB_IMG_PATH", help_text)
        self.assertIn("persistent image fallback", help_text)
        self.assertIn("persistent job default", help_text)
        self.assertIn("ECLAB_VM_IMG", help_text)
        self.assertIn("ECLAB_VM_SRC", help_text)
        self.assertIn("--eclab-vrnetlab-build-jobs COUNT", help_text)

    def test_registers_repeatable_node_image_option(self) -> None:
        registry = ArgumentRegistry()

        VrnetlabPlugin().register_arguments(registry, Mock(spec=RegistrationAPI))

        option = registry.find_exact(IMAGE_OPTION)
        self.assertIsNotNone(option)
        assert option is not None
        self.assertTrue(option.repeatable)
        self.assertFalse(option.suggest_assignment)
        self.assertEqual(option.metavar, "NODE=FILE")
        self.assertIsNone(option.environment)
        self.assertIsNotNone(option.value_completer)
        self.assertIsNotNone(option.when)
        assert option.when is not None
        self.assertFalse(
            option.when(CompletionContext(Shell.BASH, "eclab", "containerlab", ("--",), 0))
        )
        self.assertTrue(
            option.when(CompletionContext(Shell.BASH, "eclab", "containerlab", ("deploy", "--"), 1))
        )

    def test_help_and_non_deploy_calls_do_nothing(self) -> None:
        plugin = VrnetlabPlugin()
        api = self.api()

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

    def test_invalid_yaml_is_reported_as_plugin_error(self) -> None:
        with TemporaryDirectory() as directory:
            topology = Path(directory) / "lab.clab.yml"
            topology.write_text("topology: [\n", encoding="utf-8")
            with self.assertRaises(VrnetlabError):
                load_topology(topology)

    @patch("engulf_clab_vrnetlab_build.plugin.ensure_images")
    def test_deploy_without_opted_in_nodes_does_not_touch_checkout(self, ensure: Mock) -> None:
        with TemporaryDirectory() as directory:
            topology = Path(directory) / "lab.clab.yml"
            topology.write_text(
                """
name: linux-only
topology:
  nodes:
    client:
      kind: linux
      image: alpine:latest
""",
                encoding="utf-8",
            )
            plugin = VrnetlabPlugin()
            api = self.api()

            plugin.analyze_call(
                BeforeCallEvent(
                    "containerlab",
                    ("deploy", "-t", str(topology)),
                    CallMode.NORMAL,
                ),
                api,
            )

        ensure.assert_not_called()
        api.get_context.assert_not_called()
        api.state.assert_not_called()

    @patch("engulf_clab_vrnetlab_build.plugin.ensure_images")
    def test_opted_in_deploy_uses_user_state(self, ensure: Mock) -> None:
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
            plugin = VrnetlabPlugin()
            api = self.api()
            state_store = object()
            api.get_context.return_value = "/managed/vrnetlab"
            api.state.return_value = state_store
            api.require_context.return_value = TopologySession(topology, load_topology(topology))

            plugin.prepare_call(
                PreparedCallEvent(
                    "containerlab",
                    ("deploy", IMAGE_OPTION, "r1=/images/r1.qcow2"),
                    ("deploy",),
                    CallMode.NORMAL,
                ),
                api,
            )

        api.state.assert_called_once_with(StateScope.USER)
        self.assertIs(ensure.call_args.kwargs["api"], api)
        self.assertEqual(ensure.call_args.kwargs["checkout_context"], "/managed/vrnetlab")
        self.assertIs(ensure.call_args.kwargs["state_store"], state_store)
        self.assertEqual(ensure.call_args.kwargs["max_workers"], 2)
        self.assertEqual(ensure.call_args.args[0][0].source, Path("/images/r1.qcow2"))

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

    def test_image_selector_must_follow_deploy_command(self) -> None:
        api = self.api()

        contribution = VrnetlabPlugin().analyze_call(
            BeforeCallEvent(
                "containerlab",
                (IMAGE_OPTION, "default=/images/default.qcow2", "deploy"),
                CallMode.NORMAL,
            ),
            api,
        )

        self.assertIsNotNone(contribution)
        assert contribution is not None
        self.assertEqual(contribution.preempt_exit_code, 1)
        api.logger.error.assert_called_once()


class PluginProviderIntegrationTest(unittest.TestCase):
    @staticmethod
    def api() -> Mock:
        api = Mock(spec=InvocationAPI)
        api.application.display_name = "engulf-clab"
        api.application.product = "Engulf Containerlab"
        api.application.short_product_name = "eclab"
        return api

    def test_provider_registered_in_before_goal(self) -> None:
        from engulf_docker_image_api import (
            image_providers,
        )

        plugin = VrnetlabPlugin()
        api = self.api()
        contexts: dict[str, object] = {}

        def get_context(key: str, default: object = None) -> object:
            return contexts.get(key, default)

        def set_context(key: str, value: object) -> None:
            contexts[key] = value

        api.get_context.side_effect = get_context
        api.set_context.side_effect = set_context

        plugin.before_goal(Mock(), api)

        registered = image_providers(api)
        self.assertEqual(len(registered), 1)
        self.assertEqual(registered[0].provider_id, "org.engulf.docker.vrnetlab-build")
        self.assertIs(registered[0].provider, plugin._provider)

    def test_prepare_call_refreshes_provider_before_build(self) -> None:
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
            plugin = VrnetlabPlugin()
            api = self.api()
            api.get_context.return_value = "/managed/vrnetlab"
            api.require_context.return_value = TopologySession(topology, load_topology(topology))

            with (
                patch("engulf_clab_vrnetlab_build.plugin.ensure_images") as ensure,
                patch.object(
                    plugin._provider, "refresh_requests", wraps=plugin._provider.refresh_requests
                ) as refresh,
            ):
                plugin.prepare_call(
                    PreparedCallEvent(
                        "containerlab",
                        ("deploy", IMAGE_OPTION, "r1=/images/r1.qcow2"),
                        ("deploy",),
                        CallMode.NORMAL,
                    ),
                    api,
                )

            refresh.assert_called_once()
            # The map is refreshed before the staged build runs so the image-build
            # graph — driven after this prepare_call — can resolve the tag.
            self.assertLess(
                refresh.call_args.kwargs.get("checkout_context"),
                "zzz",
            )
            self.assertEqual(
                refresh.call_args.kwargs["checkout_context"],
                "/managed/vrnetlab",
            )
            self.assertEqual(refresh.call_args.args[0][0].image, "vrnetlab/vendor_router:1")
            ensure.assert_called_once()

    def test_prepare_call_refreshes_provider_even_without_sources(self) -> None:
        """A node opted in with no source still registers its reference with the
        provider so resolution reports the missing source instead of silently
        pulling."""
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
            plugin = VrnetlabPlugin()
            api = self.api()
            api.get_context.return_value = "/managed/vrnetlab"
            api.require_context.return_value = TopologySession(topology, load_topology(topology))

            with (
                patch("engulf_clab_vrnetlab_build.plugin.ensure_images") as ensure,
                patch.object(
                    plugin._provider, "refresh_requests", wraps=plugin._provider.refresh_requests
                ) as refresh,
            ):
                plugin.prepare_call(
                    PreparedCallEvent(
                        "containerlab",
                        ("deploy",),
                        ("deploy",),
                        CallMode.NORMAL,
                    ),
                    api,
                )

            refresh.assert_called_once()
            self.assertEqual(refresh.call_args.args[0][0].image, "vrnetlab/vendor_router:1")
            self.assertIsNone(refresh.call_args.args[0][0].source)
            ensure.assert_called_once()

    def test_image_plugin_shares_the_provider_instance(self) -> None:
        from engulf_clab_vrnetlab_build import image_plugin, plugin
        from engulf_clab_vrnetlab_build.provider import VRNETLAB_PROVIDER_ID

        self.assertEqual(image_plugin.plugin_id, VRNETLAB_PROVIDER_ID)
        self.assertIs(image_plugin.provider, plugin._provider)

    def test_prepare_call_precedes_image_build(self) -> None:
        from engulf_api import DependencyPosition
        from engulf_clab_schema_api import LifecycleStage

        from engulf_clab_vrnetlab_build.plugin import PLUGIN_SCHEMA

        plugin = VrnetlabPlugin()
        prepare_orderings = [
            entry
            for entry in PLUGIN_SCHEMA._ordering
            if entry.stage is LifecycleStage.PREPARE_CALL
        ]
        self.assertTrue(prepare_orderings)
        for entry in prepare_orderings:
            if "engulf_clab.image_build" in entry.before:
                break
        else:
            self.fail("schema ordering does not declare before engulf_clab.image_build")

        dependency_ids = {
            dependency.plugin_id: dependency for dependency in plugin.plugin_dependencies
        }
        self.assertIn("engulf_clab.image_build", dependency_ids)
        self.assertIs(
            dependency_ids["engulf_clab.image_build"].preprocess, DependencyPosition.AFTER
        )


if __name__ == "__main__":
    unittest.main()
