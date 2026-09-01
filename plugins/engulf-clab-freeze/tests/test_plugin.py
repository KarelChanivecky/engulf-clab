from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import tomllib
from engulf_api import (
    ApplicationMetadata,
    BeforeGoalAPI,
    GoalResultStatus,
    Invocation,
    StateScope,
    WorkspaceState,
)
from engulf_clab_freeze.plugin import FreezePlugin


class FreezePluginTest(unittest.TestCase):
    def test_dependency_is_declared_in_package_metadata(self) -> None:
        project_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
        project = tomllib.loads(project_path.read_text(encoding="utf-8"))["project"]
        group = project["entry-points"][
            "engulf.plugins.v1.dependency.engulf_clab_freeze"
        ]

        self.assertEqual(
            group,
            {"engulf_clab.schema": "preprocess=after; postprocess=none"},
        )
        self.assertNotIn("plugin_dependencies", FreezePlugin.__dict__)

    def test_freeze_runs_before_the_wrapped_goal_and_returns_its_exit_code(
        self,
    ) -> None:
        workspace = MagicMock(spec=WorkspaceState)
        workspace.root = Path("/labs/demo")
        api = MagicMock(spec=BeforeGoalAPI)
        api.get_context.return_value = None
        api.state.return_value = workspace
        api.leases.return_value.__enter__.return_value = None
        api.application = MagicMock(spec=ApplicationMetadata)
        api.application.short_product_name = "fclab"
        invocation = Invocation(
            ("freeze", "--output", "share.tar.gz"), Path("/labs/demo"), {}
        )

        with patch(
            "engulf_clab_freeze.plugin.run_freeze_command", return_value=13
        ) as command:
            result = FreezePlugin().before_goal(invocation, api)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertIs(result.status, GoalResultStatus.COMPLETED)
        self.assertEqual(result.exit_code, 13)
        api.state.assert_called_once_with(StateScope.WORKSPACE)
        # Lease name is fixed regardless of edition, so two differently-branded
        # editions freezing the same workspace concurrently block each other.
        api.leases.assert_called_once_with(("eclab-freeze:/labs/demo",))
        command.assert_called_once_with(
            ["--output", "share.tar.gz"],
            workspace,
            user_state=None,
            program="fclab freeze",
            application_name="fclab",
            logger=api.logger,
            environment=invocation.environment,
        )

    def test_offline_freeze_receives_user_state_for_managed_tools(self) -> None:
        workspace = MagicMock(spec=WorkspaceState)
        workspace.root = Path("/labs/demo")
        user_state = MagicMock(spec=WorkspaceState)
        api = MagicMock(spec=BeforeGoalAPI)
        api.get_context.return_value = None
        api.state.side_effect = lambda scope: {
            StateScope.WORKSPACE: workspace,
            StateScope.USER: user_state,
        }[scope]
        api.leases.return_value.__enter__.return_value = None
        api.application = MagicMock(spec=ApplicationMetadata)
        api.application.short_product_name = "fclab"
        invocation = Invocation(("freeze", "--offline"), Path("/labs/demo"), {})

        with patch(
            "engulf_clab_freeze.plugin.run_freeze_command", return_value=0
        ) as command:
            FreezePlugin().before_goal(invocation, api)

        command.assert_called_once_with(
            ["--offline"],
            workspace,
            user_state=user_state,
            program="fclab freeze",
            application_name="fclab",
            logger=api.logger,
            environment=invocation.environment,
        )
        self.assertEqual(
            api.state.call_args_list,
            [call(StateScope.WORKSPACE), call(StateScope.USER)],
        )
        api.leases.assert_called_once_with(
            (
                "eclab-freeze:/labs/demo",
                "repository-cache:containerlab",
                "repository-cache:vrnetlab",
            )
        )

    def test_defrost_runs_before_the_wrapped_goal_under_a_destination_lease(
        self,
    ) -> None:
        api = MagicMock(spec=BeforeGoalAPI)
        api.get_context.return_value = None
        api.leases.return_value.__enter__.return_value = None
        api.application = MagicMock(spec=ApplicationMetadata)
        api.application.short_product_name = "fclab"
        invocation = Invocation(
            ("defrost", "share.tar.gz", "--into", "demo"), Path("/labs"), {}
        )

        with patch(
            "engulf_clab_freeze.plugin.run_defrost_command", return_value=7
        ) as command:
            result = FreezePlugin().before_goal(invocation, api)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertIs(result.status, GoalResultStatus.COMPLETED)
        self.assertEqual(result.exit_code, 7)
        # Defrost writes one destination and reads no workspace state.
        api.state.assert_not_called()
        api.leases.assert_called_once_with(("eclab-defrost:/labs/demo",))
        command.assert_called_once_with(
            ["share.tar.gz", "--into", "demo"],
            program="fclab defrost",
            application_name="fclab",
            logger=api.logger,
            environment=invocation.environment,
            cwd=invocation.cwd,
        )

    def test_non_freeze_invocations_continue_to_the_wrapped_goal(self) -> None:
        api = MagicMock(spec=BeforeGoalAPI)
        api.get_context.return_value = None
        api.application = MagicMock(spec=ApplicationMetadata)
        api.application.short_product_name = "fclab"
        invocation = Invocation(("deploy", "-t", "lab.clab.yml"), Path.cwd(), {})

        with patch("engulf_clab_freeze.plugin.run_freeze_command") as command:
            result = FreezePlugin().before_goal(invocation, api)

        self.assertIsNone(result)
        command.assert_not_called()
        api.state.assert_not_called()
        api.leases.assert_not_called()

    def test_help_lists_both_control_commands(self) -> None:
        help_text = FreezePlugin().help(MagicMock())

        self.assertIn("freeze [-t TOPOLOGY]", help_text)
        self.assertIn("defrost ARCHIVE", help_text)

    def test_freeze_priority_precedes_every_other_bundled_plugin(self) -> None:
        self.assertGreater(FreezePlugin.priority, 110)


if __name__ == "__main__":
    unittest.main()
