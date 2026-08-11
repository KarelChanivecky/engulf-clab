from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from engulf_api import InvocationAPI, StateScope
from engulf_clab_ensure_vrnetlab import ENSURE_VRNETLAB_PLUGIN_ID
from engulf_executable_wrapper_api import BeforeCallEvent, CallMode, PreparedCallEvent

from engulf_clab_vrnetlab.errors import VrnetlabError
from engulf_clab_vrnetlab.plugin import VrnetlabPlugin
from engulf_clab_vrnetlab.topology import load_topology


class PluginLifecycleTest(unittest.TestCase):
    @staticmethod
    def api() -> Mock:
        api = Mock(spec=InvocationAPI)
        api.application.display_name = "engulf-clab"
        return api

    def test_ensure_vrnetlab_is_a_hard_preprocess_dependency(self) -> None:
        dependency = VrnetlabPlugin().plugin_dependencies[0]
        self.assertEqual(dependency.plugin_id, ENSURE_VRNETLAB_PLUGIN_ID)

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

    @patch("engulf_clab_vrnetlab.plugin.ensure_images")
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

    @patch("engulf_clab_vrnetlab.plugin.ensure_images")
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

            plugin.prepare_call(
                PreparedCallEvent(
                    "containerlab",
                    ("deploy", "-t", str(topology)),
                    ("deploy", "-t", str(topology)),
                    CallMode.NORMAL,
                ),
                api,
            )

        api.state.assert_called_once_with(StateScope.USER)
        self.assertIs(ensure.call_args.kwargs["api"], api)
        self.assertEqual(ensure.call_args.kwargs["checkout_context"], "/managed/vrnetlab")
        self.assertIs(ensure.call_args.kwargs["state_store"], state_store)


if __name__ == "__main__":
    unittest.main()
