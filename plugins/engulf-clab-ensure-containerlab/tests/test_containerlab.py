from __future__ import annotations

import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from engulf_clab_schema_api import ContainerlabSourceKind

from engulf_clab_ensure_containerlab.containerlab import (
    build_version_flags,
    containerlab_source_hint,
    enable_sudoless,
    ensure_binary,
    ensure_repo_binary,
    require_containerlab_dependencies,
    resolved_containerlab_source,
    sudoless_user,
)
from engulf_clab_ensure_containerlab.errors import EnsureContainerlabError


class FilesystemState:
    def __init__(self, directory: Path) -> None:
        self._directory = directory

    @property
    def directory(self) -> Path:
        self._directory.mkdir(parents=True, exist_ok=True)
        return self._directory

    def path(self, filename: str) -> Path:
        return self.directory / filename


def make_checkout(path: Path, *, binary: bool = False) -> None:
    path.mkdir(parents=True)
    (path / "go.mod").write_text("module containerlab\n", encoding="utf-8")
    if binary:
        output = path / "bin" / "containerlab"
        output.parent.mkdir()
        output.write_text("#!/bin/sh\n", encoding="utf-8")
        output.chmod(0o755)


class EnsureContainerlabTest(unittest.TestCase):
    @patch("engulf_clab_ensure_containerlab.containerlab.shutil.which", return_value=None)
    def test_missing_docker_is_reported(self, _which: Mock) -> None:
        with self.assertRaisesRegex(EnsureContainerlabError, "missing required command: docker"):
            require_containerlab_dependencies()

    @patch("engulf_clab_ensure_containerlab.containerlab.os.getuid", return_value=0)
    def test_sudoless_rejects_running_the_wrapper_as_root(self, _getuid: Mock) -> None:
        with self.assertRaisesRegex(EnsureContainerlabError, "not as root"):
            sudoless_user()

    @patch("engulf_clab_ensure_containerlab.containerlab.Path.stat")
    @patch("engulf_clab_ensure_containerlab.containerlab._run")
    @patch("engulf_clab_ensure_containerlab.containerlab.shutil.which", return_value="/usr/bin/sudo")
    @patch("engulf_clab_ensure_containerlab.containerlab.executable", return_value=True)
    def test_sudoless_establishes_group_before_enabling_root_suid(
        self,
        _executable: Mock,
        _which: Mock,
        run: Mock,
        path_stat: Mock,
    ) -> None:
        binary = Path("/opt/containerlab/bin/containerlab")
        path_stat.return_value = Mock(st_uid=0, st_gid=0, st_mode=stat.S_IFREG | 0o4755)

        enable_sudoless(binary, "alice")

        self.assertEqual(
            [item.args[0] for item in run.call_args_list],
            [
                ("sudo", "--", "groupadd", "-f", "-r", "clab_admins"),
                ("sudo", "--", "groupadd", "-f", "-r", "docker"),
                ("sudo", "--", "usermod", "-aG", "clab_admins,docker", "alice"),
                ("sudo", "--", "chown", "root:root", str(binary)),
                ("sudo", "--", "chmod", "4755", str(binary)),
            ],
        )

    def test_executable_environment_override_takes_precedence(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "containerlab"
            binary.write_text("#!/bin/sh\n", encoding="utf-8")
            binary.chmod(0o755)

            resolved = ensure_binary(
                FilesystemState(root / "state"),
                {"CONTAINERLAB_BIN": str(binary)},
            )

        self.assertEqual(resolved, binary.resolve())

    def test_source_hint_recovers_checkout_from_selected_binary(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            checkout = root / "containerlab"
            make_checkout(checkout, binary=True)
            (checkout / "schemas").mkdir()
            binary = checkout / "bin" / "containerlab"

            hint = containerlab_source_hint(
                FilesystemState(root / "state"),
                {"CONTAINERLAB_BIN": str(binary)},
            )
            resolved = resolved_containerlab_source(binary)

        self.assertIs(hint.kind, ContainerlabSourceKind.CHECKOUT)
        self.assertEqual(hint.checkout, checkout.resolve())
        self.assertFalse(hint.resolved)
        self.assertIs(resolved.kind, ContainerlabSourceKind.CHECKOUT)
        self.assertTrue(resolved.resolved)

    @patch("engulf_clab_ensure_containerlab.containerlab.shutil.which", return_value=None)
    def test_source_hint_uses_managed_checkout_before_repository(self, _which: Mock) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            managed = root / "state" / "containerlab"
            make_checkout(managed)

            hint = containerlab_source_hint(
                FilesystemState(root / "state"),
                {"CONTAINERLAB_REPO": "https://example.test/containerlab.git"},
            )

        self.assertIs(hint.kind, ContainerlabSourceKind.CHECKOUT)
        self.assertEqual(hint.checkout, managed)

    @patch("engulf_clab_ensure_containerlab.containerlab._run")
    @patch("engulf_clab_ensure_containerlab.containerlab.shutil.which")
    def test_checkout_builds_when_no_repo_binary_exists(
        self,
        which: Mock,
        run: Mock,
    ) -> None:
        which.side_effect = lambda name: "/usr/bin/go" if name == "go" else None
        with TemporaryDirectory() as directory:
            checkout = Path(directory) / "containerlab"
            make_checkout(checkout)
            output = checkout / "bin" / "containerlab"

            def build(*_args: object, **_kwargs: object) -> None:
                output.parent.mkdir(exist_ok=True)
                output.write_text("#!/bin/sh\n", encoding="utf-8")
                output.chmod(0o755)

            run.side_effect = build

            resolved = ensure_repo_binary(checkout)

        self.assertEqual(resolved, checkout / "bin" / "containerlab")
        run.assert_called_once()
        argv, kwargs = run.call_args
        # Version provenance is stamped in between `build` and `-o`; assert the
        # command's shape so the flags stay free to change.
        self.assertEqual(argv[0][:2], ("go", "build"))
        self.assertEqual(
            argv[0][-3:], ("-o", str(checkout / "bin" / "containerlab"), ".")
        )
        self.assertEqual(kwargs, {"cwd": checkout})

    @patch("engulf_clab_ensure_containerlab.containerlab.shutil.which", return_value=None)
    def test_missing_go_fails_before_build(self, _which: Mock) -> None:
        with TemporaryDirectory() as directory:
            checkout = Path(directory) / "containerlab"
            make_checkout(checkout)

            with self.assertRaisesRegex(EnsureContainerlabError, "missing required command: go"):
                ensure_repo_binary(checkout)

    @patch("engulf_clab_ensure_containerlab.containerlab.ensure_repo_binary")
    def test_valid_checkout_environment_is_built(self, build: Mock) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            checkout = root / "containerlab"
            make_checkout(checkout)
            build.return_value = checkout / "bin" / "containerlab"

            resolved = ensure_binary(
                FilesystemState(root / "state"),
                {"CONTAINERLAB_DIR": str(checkout)},
            )

        self.assertEqual(resolved, build.return_value)
        build.assert_called_once_with(checkout.resolve())


if __name__ == "__main__":
    unittest.main()


class BuildVersionFlagsTest(unittest.TestCase):
    """A plain `go build` leaves the binary reporting 0.0.0 / none / unknown."""

    @staticmethod
    def _checkout(directory: str, module: str = "github.com/srl-labs/containerlab") -> Path:
        checkout = Path(directory)
        (checkout / "go.mod").write_text(f"module {module}\n\ngo 1.24\n", encoding="utf-8")
        return checkout

    def test_symbols_use_the_module_path_declared_by_the_checkout(self) -> None:
        """A fork that renames its module must be stamped, not silently skipped."""
        with TemporaryDirectory() as directory:
            checkout = self._checkout(directory, module="example.com/fork/containerlab")

            with patch(
                "engulf_clab_ensure_containerlab.containerlab._git_output",
                return_value=None,
            ):
                flags = build_version_flags(checkout)

        self.assertEqual(len(flags), 1)
        self.assertIn("example.com/fork/containerlab/cmd.date=", flags[0])
        self.assertNotIn("srl-labs", flags[0])

    def test_git_describe_and_commit_are_stamped_when_available(self) -> None:
        with TemporaryDirectory() as directory:
            checkout = self._checkout(directory)

            with patch(
                "engulf_clab_ensure_containerlab.containerlab._git_output",
                side_effect=("v0.74.3-30-gabc1234", "abc1234"),
            ):
                flags = build_version_flags(checkout)

        self.assertIn("cmd.Version=v0.74.3-30-gabc1234", flags[0])
        self.assertIn("cmd.commit=abc1234", flags[0])

    def test_a_checkout_without_go_mod_is_built_unstamped(self) -> None:
        """Provenance is best effort: never fail a build to stamp a version."""
        with TemporaryDirectory() as directory:
            self.assertEqual(build_version_flags(Path(directory)), ())

    @patch("engulf_clab_ensure_containerlab.containerlab.executable", return_value=True)
    @patch("engulf_clab_ensure_containerlab.containerlab._run")
    @patch("engulf_clab_ensure_containerlab.containerlab.shutil.which", return_value="/usr/bin/go")
    def test_the_build_command_carries_the_flags(
        self, _which: Mock, run: Mock, _executable: Mock
    ) -> None:
        with TemporaryDirectory() as directory:
            checkout = self._checkout(directory)

            with patch(
                "engulf_clab_ensure_containerlab.containerlab._git_output",
                return_value="abc1234",
            ):
                ensure_repo_binary(checkout, rebuild=True)

        argv = run.call_args.args[0]
        self.assertEqual(argv[0], "go")
        self.assertEqual(argv[1], "build")
        self.assertTrue(argv[2].startswith("-ldflags="))
        self.assertIn("-o", argv)
