from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from engulf_clab_ensure_containerlab.containerlab import (
    ensure_binary,
    ensure_repo_binary,
    require_containerlab_dependencies,
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
        run.assert_called_once_with(
            ("go", "build", "-o", str(checkout / "bin" / "containerlab"), "."),
            cwd=checkout,
        )

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
