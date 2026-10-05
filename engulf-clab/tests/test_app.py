from __future__ import annotations

import io
import json
import os
import re
import sys
import tomllib
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
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
from engulf_clab.cli import _restore_sudo_outputs, main
from engulf_clab.workspace import workspace_root


class PackageMetadataTest(unittest.TestCase):
    def test_requires_current_runtime_release_lines(self) -> None:
        """The reset 0.1 release lines contain the required runtime contracts."""
        metadata = tomllib.loads(
            (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
        )

        self.assertIn("engulf>=0.1,<1", metadata["project"]["dependencies"])
        self.assertIn(
            "engulf-executable-wrapper>=0.2,<1",
            metadata["project"]["dependencies"],
        )
        self.assertIn(
            "engulf-executable-wrapper-api>=1.1,<2",
            metadata["project"]["dependencies"],
        )


class EditableCompletionFingerprintTest(unittest.TestCase):
    def test_editable_source_changes_invalidate_completion_metadata(self) -> None:
        class EditableDistribution:
            name = "example-plugin"
            version = "1.0.0"
            files: tuple[str, ...] = ()

            def __init__(self, project: Path) -> None:
                self.project = project

            def read_text(self, name: str) -> str | None:
                if name != "direct_url.json":
                    return None
                return json.dumps(
                    {
                        "url": self.project.as_uri(),
                        "dir_info": {"editable": True},
                    }
                )

        with TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "src" / "example_plugin"
            source.mkdir(parents=True)
            module = source / "plugin.py"
            module.write_text("FLAG = 'first'\n", encoding="utf-8")
            distribution = EditableDistribution(project)
            entry = SimpleNamespace(
                group="engulf.plugins.v1.application.engulf_clab",
                name="example.plugin",
                value="example_plugin:plugin",
                dist=distribution,
            )
            with patch.object(
                app_module.importlib.metadata,
                "entry_points",
                return_value=(entry,),
            ):
                first = app_module.completion_installed_metadata()
                module.write_text("FLAG = 'other'\n", encoding="utf-8")
                second = app_module.completion_installed_metadata()

        self.assertNotEqual(first["entry_points"], second["entry_points"])


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


class SudoArtifactRestorationTest(unittest.TestCase):
    def test_cli_restores_artifacts_after_the_goal(self) -> None:
        application = MagicMock()
        application.goal = object()
        application.run.return_value = 12
        manager = MagicMock()
        manager.__enter__.return_value = application
        manager.__exit__.return_value = False

        with (
            patch(
                "engulf_clab.cli.CONTAINERLAB_APPLICATION",
                SimpleNamespace(create=MagicMock(return_value=manager)),
            ),
            patch("engulf_clab.cli._restore_sudo_outputs") as restore,
            patch("engulf_clab.cli.sys.argv", ["eclab", "deploy"]),
        ):
            self.assertEqual(main(), 12)

        restore.assert_called_once_with(("deploy",))

    def test_restores_user_state_completion_and_selected_workspace(self) -> None:
        home = Path("/home/alice")
        workspace = Path("/labs/demo")
        completion = home / ".cache" / "engulf-clab" / "completion.json"
        environment = {
            "SUDO_UID": "1001",
            "SUDO_GID": "1002",
            "HOME": str(home),
        }

        with (
            patch.dict(os.environ, environment, clear=True),
            patch("engulf_clab.cli.os.geteuid", return_value=0),
            patch("pwd.getpwuid", return_value=SimpleNamespace(pw_dir=str(home), pw_gid=1002)),
            patch("engulf_clab.cli.workspace_root", return_value=workspace),
            patch("engulf_clab.cli.completion_artifact_path", return_value=completion),
            patch("engulf_clab.cli.restore_sudo_ownership") as restore,
        ):
            _restore_sudo_outputs(("deploy", "-t", "lab.clab.yml"))

        self.assertEqual(
            [entry.args[0] for entry in restore.call_args_list],
            [
                home / ".local" / "state" / "engulf-clab",
                workspace,
                completion,
            ],
        )

    def test_help_does_not_traverse_the_workspace(self) -> None:
        home = Path("/home/alice")
        environment = {"SUDO_UID": "1001", "SUDO_GID": "1002", "HOME": str(home)}
        with (
            patch.dict(os.environ, environment, clear=True),
            patch("engulf_clab.cli.os.geteuid", return_value=0),
            patch("pwd.getpwuid", return_value=SimpleNamespace(pw_dir=str(home), pw_gid=1002)),
            patch("engulf_clab.cli.completion_artifact_path", return_value=home / "cache"),
            patch("engulf_clab.cli.restore_sudo_ownership") as restore,
            patch("engulf_clab.cli.workspace_root") as workspace_root_resolver,
        ):
            _restore_sudo_outputs(("deploy", "--help"))

        self.assertEqual(restore.call_count, 2)
        workspace_root_resolver.assert_not_called()


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

    def test_plugin_list_uses_a_metadata_fallback_when_extension_is_absent(
        self,
    ) -> None:
        definition = MagicMock()
        application = definition.create.return_value.__enter__.return_value
        application.diagnostic_extensions = ()
        application.active_plugins = ()
        application.postprocess_plugins = ()
        output = io.StringIO()
        with (
            patch("engulf_clab.cli.CONTAINERLAB_APPLICATION", definition),
            patch.object(sys, "argv", ["eclab", "--engulf-plugin-list"]),
            redirect_stdout(output),
        ):
            self.assertEqual(main(), 0)

        self.assertIn("Normal goal plugins", output.getvalue())
        self.assertIn("Diagnostic extensions", output.getvalue())
        application.run.assert_not_called()


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
                CONTAINERLAB_APPLICATION.create(discover_installed=discover_installed)

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
