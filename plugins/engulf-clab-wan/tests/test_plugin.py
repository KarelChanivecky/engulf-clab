from __future__ import annotations

import unittest
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, call, patch

from engulf_api import InvocationAPI, StateScope, StateStore, WorkspaceState
from engulf_executable_wrapper_api import (
    AfterCallEvent,
    CallMode,
    CallOutcome,
    OutcomeKind,
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


class PluginStateLifecycleTest(unittest.TestCase):
    @patch("engulf_clab_wan.plugin.setup_dhcp_wan_bridges")
    def test_deploy_uses_current_workspace_state(self, setup: Mock) -> None:
        with TemporaryDirectory() as directory:
            topology = Path(directory) / "lab.clab.yml"
            topology.write_text(
                "topology:\n  nodes:\n    wan:\n      kind: bridge\n"
                "      labels: {FCLAB_DHCP_WAN: 'true'}\n",
                encoding="utf-8",
            )
            workspace = Mock(spec=WorkspaceState)
            user_state = Mock(spec=StateStore)
            api = Mock(spec=InvocationAPI)
            api.leases.return_value = nullcontext()
            api.state.side_effect = lambda scope: (
                workspace if scope is StateScope.WORKSPACE else user_state
            )

            WanPlugin().prepare_call(
                PreparedCallEvent(
                    "containerlab",
                    ("deploy", "-t", str(topology)),
                    ("deploy", "-t", str(topology)),
                    CallMode.NORMAL,
                ),
                api,
            )

        self.assertEqual(api.state.call_count, 2)
        self.assertIs(setup.call_args.args[1], workspace)
        self.assertIs(setup.call_args.args[2], user_state)

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
