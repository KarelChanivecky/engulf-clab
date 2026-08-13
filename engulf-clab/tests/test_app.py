from __future__ import annotations

import os
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from engulf import Application, ApplicationDefinition
from engulf_api import GoalAPI, Invocation, StateScope, WorkspaceState
from engulf_executable_wrapper import ExecutableWrapperGoal

from engulf_clab import (
    APPLICATION_ID,
    CONTAINERLAB_APPLICATION,
    DISPLAY_NAME,
    VENDOR,
    ContainerlabApp,
    binary_path,
)
from engulf_clab.cli import _freeze, main
from engulf_clab.freeze_control import FreezeGoal, run_freeze_command
from engulf_clab.workspace import workspace_root


class BinaryPathTest(unittest.TestCase):
    def test_uses_containerlab_dir_when_it_contains_binary(self) -> None:
        with TemporaryDirectory() as directory:
            binary = Path(directory) / "containerlab"
            binary.touch()
            with patch.dict(os.environ, {"CONTAINERLAB_DIR": directory}):
                self.assertEqual(binary_path(), str(binary))

    def test_falls_back_to_path_name_when_binary_is_absent(self) -> None:
        with patch.dict(os.environ, {"CONTAINERLAB_DIR": "/missing"}):
            self.assertEqual(binary_path(), "containerlab")


class ContainerlabAppTest(unittest.TestCase):
    def test_public_definition_supports_separately_released_editions(self) -> None:
        edition = CONTAINERLAB_APPLICATION.edition(
            display_name="vendor-clab",
            vendor="Vendor Networks",
        )

        self.assertIsInstance(CONTAINERLAB_APPLICATION, ApplicationDefinition)
        self.assertEqual(edition.application_id, APPLICATION_ID)
        self.assertEqual(edition.display_name, "vendor-clab")
        self.assertEqual(edition.vendor, "Vendor Networks")
        self.assertEqual(edition.display_name, "vendor-clab")
        self.assertEqual(CONTAINERLAB_APPLICATION.vendor, VENDOR)
        self.assertIs(edition.goal_factory, CONTAINERLAB_APPLICATION.goal_factory)

    def test_is_an_engulf_application_with_containerlab_defaults(self) -> None:
        app = ContainerlabApp(discover_installed=False)

        self.assertIsInstance(app, Application)
        self.assertIsInstance(app.goal, ExecutableWrapperGoal)
        self.assertEqual(app.application_id, APPLICATION_ID)
        self.assertEqual(app.display_name, DISPLAY_NAME)
        self.assertIs(app._workspace_root_resolver, workspace_root)

    def test_accepts_extension_configuration(self) -> None:
        app = ContainerlabApp(
            "/custom/containerlab",
            application_id="my-containerlab",
            discover_installed=False,
        )

        self.assertEqual(app.binary, "/custom/containerlab")
        self.assertEqual(app.application_id, "my-containerlab")


class CliTest(unittest.TestCase):
    def test_main_runs_a_fresh_public_definition_application(self) -> None:
        definition = MagicMock()
        with patch("engulf_clab.cli.CONTAINERLAB_APPLICATION", definition):
            application = definition.create.return_value.__enter__.return_value
            application.run.return_value = 23

            self.assertEqual(main(), 23)

        definition.create.assert_called_once_with()
        application.run.assert_called_once_with()

    def test_freeze_uses_the_managed_workspace_runner(self) -> None:
        point = MagicMock()
        command = MagicMock(return_value=0)
        point.name = "freeze"
        point.load.return_value = command
        with (
            patch("engulf_clab.cli.importlib.metadata.entry_points", return_value=(point,)),
            patch("engulf_clab.cli.run_freeze_command", return_value=19) as runner,
        ):
            self.assertEqual(_freeze(("--output", "share.tar.gz")), 19)

        runner.assert_called_once_with(CONTAINERLAB_APPLICATION, command, ("--output", "share.tar.gz"))


class FreezeGoalTest(unittest.TestCase):
    def test_freeze_goal_uses_workspace_state_and_a_workspace_lease(self) -> None:
        root = Path("/labs/demo")
        workspace = MagicMock(spec=WorkspaceState)
        workspace.root = root
        api = MagicMock(spec=GoalAPI)
        api.state.return_value = workspace
        api.leases.return_value.__enter__.return_value = None
        command = MagicMock(return_value=13)
        invocation = Invocation(("--output", "share.tar.gz"), root, {})

        result = FreezeGoal(command).achieve(invocation, api)

        self.assertEqual(result.exit_code, 13)
        api.state.assert_called_once_with(StateScope.WORKSPACE)
        api.leases.assert_called_once_with(("eclab-freeze:/labs/demo",))
        command.assert_called_once_with(["--output", "share.tar.gz"], workspace)

    def test_managed_runner_keeps_workspace_state_between_freezes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "lab"
            root.mkdir()
            topology = root / "lab.clab.yml"
            topology.write_text("topology: {nodes: {}}\n", encoding="utf-8")
            state_home = Path(directory) / "state"
            definition = replace(
                CONTAINERLAB_APPLICATION,
                state_home_resolver=lambda _context: state_home,
            )

            def record(_arguments: list[str], workspace: WorkspaceState) -> int:
                workspace.write_text("freeze-marker.txt", "recorded\n")
                return 0

            observed: list[tuple[Path, str]] = []

            def inspect(_arguments: list[str], workspace: WorkspaceState) -> int:
                observed.append((workspace.root, workspace.read_text("freeze-marker.txt")))
                return 0

            arguments = ("-t", str(topology))
            self.assertEqual(run_freeze_command(definition, record, arguments), 0)
            self.assertEqual(run_freeze_command(definition, inspect, arguments), 0)
            self.assertEqual(observed, [(root.resolve(), "recorded\n")])


if __name__ == "__main__":
    unittest.main()
