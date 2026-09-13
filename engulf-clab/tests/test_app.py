from __future__ import annotations

import io
import os
import re
import tomllib
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from engulf import (
    FRAMEWORK_ERROR_EXIT,
    Application,
    ApplicationDefinition,
    GoalPrivilegeError,
)
from engulf_executable_wrapper import ExecutableWrapperGoal

from engulf_clab import (
    APPLICATION_ID,
    CONTAINERLAB_APPLICATION,
    DISPLAY_NAME,
    VENDOR,
    ContainerlabApp,
    binary_path,
)
from engulf_clab import app as app_module
from engulf_clab.cli import main
from engulf_clab.workspace import workspace_root


class PackageMetadataTest(unittest.TestCase):
    def test_requires_runtime_versions_with_source_completion_support(self) -> None:
        """Engulf 0.3 gates elevated startup and reads plugin ordering.

        An older runtime cannot enforce eclab's unprivileged launcher contract,
        so the floor has to exclude the 0.2 line.
        """
        metadata = tomllib.loads(
            (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
        )

        self.assertIn("engulf>=0.3,<1", metadata["project"]["dependencies"])
        self.assertIn(
            "engulf-executable-wrapper>=0.3,<1",
            metadata["project"]["dependencies"],
        )


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

    def test_finds_a_companion_binary_beside_the_console_script(self) -> None:
        """An unactivated venv leaves its bin off PATH, which is the whole cause
        of the `command not found: containerlab` exit 127.
        """
        with TemporaryDirectory() as directory:
            bin_dir = Path(directory) / "bin"
            bin_dir.mkdir()
            companion = bin_dir / "containerlab"
            companion.write_text("#!/bin/sh\n", encoding="utf-8")
            companion.chmod(0o755)

            with (
                patch.dict(os.environ, {}, clear=True),
                patch.object(app_module.sys, "executable", str(bin_dir / "python")),
            ):
                self.assertEqual(binary_path(), str(companion))

    def test_a_companion_lookup_does_not_follow_the_interpreter_symlink(self) -> None:
        """A venv python is normally a symlink to the system interpreter, so
        resolving it would escape the environment and select a system binary.
        """
        with TemporaryDirectory() as directory:
            system_bin = Path(directory) / "usr-bin"
            system_bin.mkdir()
            unrelated = system_bin / "containerlab"
            unrelated.write_text("#!/bin/sh\n", encoding="utf-8")
            unrelated.chmod(0o755)

            venv_bin = Path(directory) / "venv-bin"
            venv_bin.mkdir()
            (system_bin / "python").write_text("#!/bin/sh\n", encoding="utf-8")
            (venv_bin / "python").symlink_to(system_bin / "python")

            with (
                patch.dict(os.environ, {}, clear=True),
                patch.object(app_module.sys, "executable", str(venv_bin / "python")),
            ):
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


class PrivilegeRefusalTest(unittest.TestCase):
    """eclab refuses elevated startup; the goal stays opted out by contract."""

    def test_elevated_startup_is_refused(self) -> None:
        for discover_installed in (True, False):
            with (
                self.subTest(discover_installed=discover_installed),
                patch(
                    "engulf.application.is_process_elevated",
                    return_value=True,
                ),
                self.assertRaises(GoalPrivilegeError),
            ):
                CONTAINERLAB_APPLICATION.create(
                    discover_installed=discover_installed
                )

    def test_unprivileged_startup_still_works(self) -> None:
        with (
            patch("engulf.application.is_process_elevated", return_value=False),
            CONTAINERLAB_APPLICATION.create(discover_installed=False) as app,
        ):
            self.assertFalse(app.elevated)

    def test_launcher_reports_refusal_with_framework_exit(self) -> None:
        stderr = io.StringIO()
        with (
            patch("engulf.application.is_process_elevated", return_value=True),
            redirect_stderr(stderr),
        ):
            result = main()
        self.assertEqual(result, FRAMEWORK_ERROR_EXIT)
        self.assertIn("eclab:", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_no_distribution_opts_the_goal_into_privilege(self) -> None:
        # Any `engulf.privilege_opt_in.*` declaration in this monorepo would
        # silently authorize elevated startup; the refusal is the contract.
        repository_root = Path(__file__).resolve().parents[2]
        offenders = [
            path.relative_to(repository_root).as_posix()
            for path in sorted(repository_root.rglob("pyproject.toml"))
            if ".venv" not in path.parts
            and "privilege_opt_in" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()


class VersionSourceTest(unittest.TestCase):
    """The reported version identifies a build in a bug report, so it must come
    from package metadata. A hand-maintained constant drifts from
    `pyproject.toml` silently, which is exactly how 0.1.0 was still reported
    against a 0.2.0 distribution.
    """

    def test_version_is_read_from_installed_package_metadata(self) -> None:
        import importlib.metadata

        from engulf_clab.app import VERSION

        self.assertEqual(VERSION, importlib.metadata.version("engulf-clab"))

    def test_no_hardcoded_version_literal_remains_in_the_module(self) -> None:
        source = (
            Path(__file__).parents[1] / "src" / "engulf_clab" / "app.py"
        ).read_text(encoding="utf-8")

        self.assertIsNone(
            re.search(r'^VERSION\s*=\s*[\'"]\d', source, re.MULTILINE),
            "VERSION must be derived from package metadata, not assigned a literal",
        )
