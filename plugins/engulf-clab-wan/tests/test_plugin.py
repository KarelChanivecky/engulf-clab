from __future__ import annotations

import tomllib
import unittest
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, call, patch

from engulf_api import InvocationAPI, StateScope, StateStore, WorkspaceState
from engulf_clab_lab_parser import TopologySession, load_topology
from engulf_executable_wrapper_api import (
    AfterCallEvent,
    CallMode,
    CallOutcome,
    HelpAPI,
    OutcomeKind,
    PreparationFailedEvent,
    PreparedCallEvent,
)

from engulf_clab_wan.errors import WanError
from engulf_clab_wan.plugin import WanPlugin, destroy_all_requested


def completed_destroy(*args: str) -> AfterCallEvent:
    wrapper_args = ("destroy", *args)
    return AfterCallEvent(
        binary="containerlab",
        wrapper_args=wrapper_args,
        effective_args=wrapper_args,
        mode=CallMode.NORMAL,
        outcome=CallOutcome(OutcomeKind.COMPLETED, 0, process_started=True),
        duration_seconds=0.1,
    )


class DestroyAllOptionTest(unittest.TestCase):
    def test_recognizes_long_short_and_assigned_flags(self) -> None:
        for args in (("-a",), ("--all",), ("--all=true",)):
            with self.subTest(args=args):
                self.assertTrue(destroy_all_requested(args))

    def test_false_or_absent_flag_is_not_all(self) -> None:
        self.assertFalse(destroy_all_requested(()))
        self.assertFalse(destroy_all_requested(("--all=false",)))


class HelpTest(unittest.TestCase):
    def test_help_uses_fixed_prefix_regardless_of_edition(self) -> None:
        api = Mock(spec=HelpAPI)
        api.application.short_product_name = "vendor clab"
        api.application.product = "Vendor Containerlab"

        rendered = WanPlugin().help(api)

        self.assertIn("ECLAB_DHCP_WAN", rendered)
        self.assertNotIn("VENDOR_CLAB_DHCP_WAN", rendered)


class PluginStateLifecycleTest(unittest.TestCase):
    @patch("engulf_clab_wan.plugin.workspace_bridge_names", return_value=[])
    @patch("engulf_clab_wan.plugin.setup_dhcp_wan_bridges")
    def test_deploy_uses_current_workspace_state(
        self, setup: Mock, _names: Mock
    ) -> None:
        with TemporaryDirectory() as directory:
            topology = Path(directory) / "lab.clab.yml"
            topology.write_text(
                "topology:\n  nodes:\n    wan:\n      kind: bridge\n"
                "      labels: {ECLAB_DHCP_WAN: 'true'}\n",
                encoding="utf-8",
            )
            workspace = Mock(spec=WorkspaceState)
            user_state = Mock(spec=StateStore)
            api = Mock(spec=InvocationAPI)
            api.application.short_product_name = "eclab"
            api.application.product = "Engulf Containerlab"
            api.leases.return_value = nullcontext()
            session = TopologySession(topology, load_topology(topology))
            api.require_context.return_value = session
            api.state.side_effect = lambda scope: (
                workspace if scope is StateScope.WORKSPACE else user_state
            )

            WanPlugin().prepare_call(
                PreparedCallEvent(
                    "containerlab",
                    ("deploy",),
                    ("deploy",),
                    CallMode.NORMAL,
                ),
                api,
            )

        self.assertEqual(api.state.call_count, 2)
        self.assertIs(setup.call_args.args[1], workspace)
        self.assertIs(setup.call_args.args[2], user_state)
        self.assertEqual(setup.call_args.args[3].prefix, "ECLAB")
        self.assertEqual(
            session.materialize()["topology"]["nodes"]["wan"]["labels"], {}
        )

    @patch("engulf_clab_wan.plugin.workspace_bridge_names", return_value=["wan"])
    @patch("engulf_clab_wan.plugin.cleanup_dhcp_wan_bridges")
    def test_destroy_uses_current_workspace_state(
        self, cleanup: Mock, _names: Mock
    ) -> None:
        workspace = Mock(spec=WorkspaceState)
        user_state = Mock(spec=StateStore)
        api = Mock(spec=InvocationAPI)
        api.leases.return_value = nullcontext()
        api.state.side_effect = lambda scope: (
            workspace if scope is StateScope.WORKSPACE else user_state
        )

        WanPlugin().after_call(completed_destroy(), api)

        self.assertEqual(api.state.call_count, 2)
        api.known_workspaces.assert_not_called()
        cleanup.assert_called_once_with(workspace, user_state)

    @patch(
        "engulf_clab_wan.plugin.workspace_bridge_names", side_effect=(["wan"], ["wan2"])
    )
    @patch("engulf_clab_wan.plugin.cleanup_dhcp_wan_bridges")
    def test_destroy_all_cleans_every_known_workspace(
        self, cleanup: Mock, _names: Mock
    ) -> None:
        first = Mock(spec=WorkspaceState)
        second = Mock(spec=WorkspaceState)
        api = Mock(spec=InvocationAPI)
        api.known_workspaces.return_value = (first, second)
        api.leases.return_value = nullcontext()
        user_state = Mock(spec=StateStore)
        api.state.return_value = user_state

        WanPlugin().after_call(completed_destroy("--all"), api)

        api.known_workspaces.assert_called_once_with()
        api.state.assert_called_once_with(StateScope.USER)
        self.assertEqual(
            cleanup.call_args_list, [call(first, user_state), call(second, user_state)]
        )

    @patch(
        "engulf_clab_wan.plugin.workspace_bridge_names", side_effect=(["wan"], ["wan2"])
    )
    @patch("engulf_clab_wan.plugin.cleanup_dhcp_wan_bridges")
    def test_destroy_all_attempts_remaining_workspaces_after_failure(
        self, cleanup: Mock, _names: Mock
    ) -> None:
        first = Mock(spec=WorkspaceState)
        first.root = Path("/labs/first")
        second = Mock(spec=WorkspaceState)
        second.root = Path("/labs/second")
        api = Mock(spec=InvocationAPI)
        api.known_workspaces.return_value = (first, second)
        api.leases.return_value = nullcontext()
        user_state = Mock(spec=StateStore)
        api.state.return_value = user_state
        cleanup.side_effect = (WanError("first failed"), None)

        with self.assertRaisesRegex(WanError, "/labs/first"):
            WanPlugin().after_call(completed_destroy("-a"), api)

        self.assertEqual(
            cleanup.call_args_list,
            [call(first, user_state), call(second, user_state)],
        )


if __name__ == "__main__":
    unittest.main()


class PackagingTest(unittest.TestCase):
    def test_dependency_is_declared_in_package_metadata(self) -> None:
        project_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
        project = tomllib.loads(project_path.read_text(encoding="utf-8"))["project"]
        group = project["entry-points"]["engulf.plugins.v1.dependency.engulf_clab_wan"]

        self.assertEqual(
            group,
            {
                "engulf_clab.lab_parser": "preprocess=before; postprocess=none",
                "engulf_clab.lab_writer": "preprocess=after; postprocess=none",
                "engulf_clab.schema": "preprocess=after; postprocess=none",
            },
        )
        self.assertNotIn("plugin_dependencies", WanPlugin.__dict__)


class PreparationUnwindTest(unittest.TestCase):
    """A deploy that never runs must not leave this invocation's bridges behind."""

    @staticmethod
    def _api(workspace: Mock, user_state: Mock) -> Mock:
        contexts: dict[str, object] = {}
        api = Mock(spec=InvocationAPI)
        api.application.short_product_name = "eclab"
        api.application.product = "Engulf Containerlab"
        api.leases.return_value = nullcontext()
        api.state.side_effect = lambda scope: (
            workspace if scope is StateScope.WORKSPACE else user_state
        )
        api.set_context.side_effect = contexts.__setitem__
        api.get_context.side_effect = lambda key, default=None: contexts.get(
            key, default
        )
        return api

    def _deploy(self, api: Mock, directory: str) -> WanPlugin:
        topology = Path(directory) / "lab.clab.yml"
        topology.write_text(
            "topology:\n  nodes:\n    wan:\n      kind: bridge\n"
            "      labels: {ECLAB_DHCP_WAN: 'true'}\n",
            encoding="utf-8",
        )
        api.require_context.return_value = TopologySession(
            topology, load_topology(topology)
        )
        plugin = WanPlugin()
        plugin.prepare_call(
            PreparedCallEvent("containerlab", ("deploy",), ("deploy",), CallMode.NORMAL),
            api,
        )
        return plugin

    @patch("engulf_clab_wan.plugin.bridge_metadata_for_workspace")
    @patch("engulf_clab_wan.plugin.release_workspace_bridges")
    @patch("engulf_clab_wan.plugin.setup_dhcp_wan_bridges")
    @patch(
        "engulf_clab_wan.plugin.workspace_bridge_names",
        side_effect=([], ["wan"]),
    )
    def test_releases_the_bridges_this_invocation_claimed(
        self, _names: Mock, _setup: Mock, release: Mock, metadata: Mock
    ) -> None:
        workspace = Mock(spec=WorkspaceState)
        user_state = Mock(spec=StateStore)
        api = self._api(workspace, user_state)

        with TemporaryDirectory() as directory:
            plugin = self._deploy(api, directory)

        plugin.prepare_failed(
            PreparationFailedEvent(
                "containerlab", ("deploy",), ("deploy",), CallMode.NORMAL, "later plugin failed"
            ),
            api,
        )

        release.assert_called_once_with(("wan",), workspace, user_state)
        metadata.assert_called_once_with(workspace, [])

    @patch("engulf_clab_wan.plugin.bridge_metadata_for_workspace")
    @patch("engulf_clab_wan.plugin.release_workspace_bridges")
    @patch("engulf_clab_wan.plugin.setup_dhcp_wan_bridges")
    @patch(
        "engulf_clab_wan.plugin.workspace_bridge_names",
        side_effect=(["wan"], ["wan", "wan2"]),
    )
    def test_keeps_bridges_a_previous_deploy_still_owns(
        self, _names: Mock, _setup: Mock, release: Mock, metadata: Mock
    ) -> None:
        workspace = Mock(spec=WorkspaceState)
        user_state = Mock(spec=StateStore)
        api = self._api(workspace, user_state)

        with TemporaryDirectory() as directory:
            plugin = self._deploy(api, directory)

        plugin.prepare_failed(
            PreparationFailedEvent(
                "containerlab", ("deploy",), ("deploy",), CallMode.NORMAL, "later plugin failed"
            ),
            api,
        )

        release.assert_called_once_with(("wan2",), workspace, user_state)
        metadata.assert_called_once_with(workspace, ["wan"])

    @patch("engulf_clab_wan.plugin.bridge_metadata_for_workspace")
    @patch("engulf_clab_wan.plugin.release_workspace_bridges")
    @patch("engulf_clab_wan.plugin.setup_dhcp_wan_bridges")
    @patch(
        "engulf_clab_wan.plugin.workspace_bridge_names",
        side_effect=(["wan"], ["wan"]),
    )
    def test_a_redeploy_that_claimed_nothing_new_releases_nothing(
        self, _names: Mock, _setup: Mock, release: Mock, metadata: Mock
    ) -> None:
        workspace = Mock(spec=WorkspaceState)
        user_state = Mock(spec=StateStore)
        api = self._api(workspace, user_state)

        with TemporaryDirectory() as directory:
            plugin = self._deploy(api, directory)

        plugin.prepare_failed(
            PreparationFailedEvent(
                "containerlab", ("deploy",), ("deploy",), CallMode.NORMAL, "later plugin failed"
            ),
            api,
        )

        release.assert_not_called()
        metadata.assert_not_called()

    def test_unwind_ignores_commands_other_than_deploy(self) -> None:
        api = Mock(spec=InvocationAPI)

        WanPlugin().prepare_failed(
            PreparationFailedEvent(
                "containerlab", ("destroy",), ("destroy",), CallMode.NORMAL, "failed"
            ),
            api,
        )

        api.get_context.assert_not_called()


class OwnPreparationFailureTest(unittest.TestCase):
    """Engulf skips prepare_failed for the plugin that raised, so setup self-unwinds."""

    @patch("engulf_clab_wan.plugin.bridge_metadata_for_workspace")
    @patch("engulf_clab_wan.plugin.release_workspace_bridges")
    @patch(
        "engulf_clab_wan.plugin.setup_dhcp_wan_bridges",
        side_effect=WanError("second bridge failed"),
    )
    @patch(
        "engulf_clab_wan.plugin.workspace_bridge_names",
        side_effect=(["wan"], ["wan", "wan2"]),
    )
    def test_setup_failure_releases_the_bridges_it_already_claimed(
        self, _names: Mock, _setup: Mock, release: Mock, metadata: Mock
    ) -> None:
        workspace = Mock(spec=WorkspaceState)
        user_state = Mock(spec=StateStore)
        contexts: dict[str, object] = {}
        api = Mock(spec=InvocationAPI)
        api.application.short_product_name = "eclab"
        api.application.product = "Engulf Containerlab"
        api.leases.return_value = nullcontext()
        api.state.side_effect = lambda scope: (
            workspace if scope is StateScope.WORKSPACE else user_state
        )
        api.set_context.side_effect = contexts.__setitem__
        api.get_context.side_effect = lambda key, default=None: contexts.get(key, default)

        with TemporaryDirectory() as directory:
            topology = Path(directory) / "lab.clab.yml"
            topology.write_text(
                "topology:\n  nodes:\n    wan:\n      kind: bridge\n"
                "      labels: {ECLAB_DHCP_WAN: 'true'}\n",
                encoding="utf-8",
            )
            api.require_context.return_value = TopologySession(
                topology, load_topology(topology)
            )

            with self.assertRaises(WanError):
                WanPlugin().prepare_call(
                    PreparedCallEvent(
                        "containerlab", ("deploy",), ("deploy",), CallMode.NORMAL
                    ),
                    api,
                )

        # Only the bridge this attempt added is released; "wan" predates it.
        release.assert_called_once_with(("wan2",), workspace, user_state)
        metadata.assert_called_once_with(workspace, ["wan"])

    @patch("engulf_clab_wan.plugin.bridge_metadata_for_workspace")
    @patch("engulf_clab_wan.plugin.release_workspace_bridges")
    @patch(
        "engulf_clab_wan.plugin.setup_dhcp_wan_bridges",
        side_effect=KeyboardInterrupt(),
    )
    @patch(
        "engulf_clab_wan.plugin.workspace_bridge_names",
        side_effect=(["wan"], ["wan", "wan2"]),
    )
    def test_an_interrupt_also_releases_this_attempts_bridges(
        self, _names: Mock, _setup: Mock, release: Mock, metadata: Mock
    ) -> None:
        """Ctrl-C in this plugin's own callback must still self-release.

        The goal unwinds every plugin that prepared before this one on an
        interrupt, but never the plugin that raised. An interrupt is not an
        Exception, so narrowing the except BaseException handler in
        _setup_before_deploy would strand a live host bridge nothing else releases.
        """
        workspace = Mock(spec=WorkspaceState)
        user_state = Mock(spec=StateStore)
        contexts: dict[str, object] = {}
        api = Mock(spec=InvocationAPI)
        api.application.short_product_name = "eclab"
        api.application.product = "Engulf Containerlab"
        api.leases.return_value = nullcontext()
        api.state.side_effect = lambda scope: (
            workspace if scope is StateScope.WORKSPACE else user_state
        )
        api.set_context.side_effect = contexts.__setitem__
        api.get_context.side_effect = lambda key, default=None: contexts.get(key, default)

        with TemporaryDirectory() as directory:
            topology = Path(directory) / "lab.clab.yml"
            topology.write_text(
                "topology:\n  nodes:\n    wan:\n      kind: bridge\n"
                "      labels: {ECLAB_DHCP_WAN: 'true'}\n",
                encoding="utf-8",
            )
            api.require_context.return_value = TopologySession(
                topology, load_topology(topology)
            )

            with self.assertRaises(KeyboardInterrupt):
                WanPlugin().prepare_call(
                    PreparedCallEvent(
                        "containerlab", ("deploy",), ("deploy",), CallMode.NORMAL
                    ),
                    api,
                )

        release.assert_called_once_with(("wan2",), workspace, user_state)
        metadata.assert_called_once_with(workspace, ["wan"])

    @patch("engulf_clab_wan.plugin.bridge_metadata_for_workspace")
    @patch("engulf_clab_wan.plugin.release_workspace_bridges")
    @patch(
        "engulf_clab_wan.plugin.setup_dhcp_wan_bridges",
        side_effect=WanError("second bridge failed"),
    )
    @patch(
        "engulf_clab_wan.plugin.workspace_bridge_names",
        side_effect=(["wan"], ["wan", "wan2"]),
    )
    def test_self_unwind_does_not_nest_resource_leases(
        self, _names: Mock, _setup: Mock, _release: Mock, _metadata: Mock
    ) -> None:
        """Engulf rejects nested leases; the self-unwind runs under the ones held."""
        workspace = Mock(spec=WorkspaceState)
        user_state = Mock(spec=StateStore)
        contexts: dict[str, object] = {}
        depth = 0

        @contextmanager
        def exclusive_leases(*_args: object, **_kwargs: object) -> Iterator[None]:
            nonlocal depth
            if depth:  # Mirrors engulf's _capabilities.claim_leases guard.
                raise RuntimeError(
                    "nested or overlapping resource leases are not allowed"
                )
            depth += 1
            try:
                yield
            finally:
                depth -= 1

        api = Mock(spec=InvocationAPI)
        api.application.short_product_name = "eclab"
        api.application.product = "Engulf Containerlab"
        api.leases.side_effect = exclusive_leases
        api.state.side_effect = lambda scope: (
            workspace if scope is StateScope.WORKSPACE else user_state
        )
        api.set_context.side_effect = contexts.__setitem__
        api.get_context.side_effect = lambda key, default=None: contexts.get(key, default)

        with TemporaryDirectory() as directory:
            topology = Path(directory) / "lab.clab.yml"
            topology.write_text(
                "topology:\n  nodes:\n    wan:\n      kind: bridge\n"
                "      labels: {ECLAB_DHCP_WAN: 'true'}\n",
                encoding="utf-8",
            )
            api.require_context.return_value = TopologySession(
                topology, load_topology(topology)
            )

            # The original cause must survive: a nested lease would replace it.
            with self.assertRaises(WanError):
                WanPlugin().prepare_call(
                    PreparedCallEvent(
                        "containerlab", ("deploy",), ("deploy",), CallMode.NORMAL
                    ),
                    api,
                )
