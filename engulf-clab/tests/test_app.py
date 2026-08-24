from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from engulf import Application, ApplicationDefinition
from engulf_executable_wrapper import ExecutableWrapperGoal

from engulf_clab import (
    APPLICATION_ID,
    CONTAINERLAB_APPLICATION,
    DISPLAY_NAME,
    VENDOR,
    ContainerlabApp,
    binary_path,
)
from engulf_clab.cli import main
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
        self.assertTrue(app.goal.source_completion)
        self.assertIs(app._workspace_root_resolver, workspace_root)

    def test_accepts_extension_configuration(self) -> None:
        app = ContainerlabApp(
            "/custom/containerlab",
            application_id="my-containerlab",
            discover_installed=False,
            source_completion=False,
        )

        self.assertEqual(app.binary, "/custom/containerlab")
        self.assertEqual(app.application_id, "my-containerlab")
        self.assertFalse(app.goal.source_completion)


class CliTest(unittest.TestCase):
    def test_main_runs_a_fresh_public_definition_application(self) -> None:
        definition = MagicMock()
        with patch("engulf_clab.cli.CONTAINERLAB_APPLICATION", definition):
            application = definition.create.return_value.__enter__.return_value
            application.run.return_value = 23

            self.assertEqual(main(), 23)

        definition.create.assert_called_once_with()
        application.run.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
