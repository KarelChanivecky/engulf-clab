from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from engulf_clab_ensure_vrnetlab.checkout import ensure_checkout
from engulf_clab_ensure_vrnetlab.errors import EnsureVrnetlabError


class FilesystemState:
    def __init__(self, directory: Path) -> None:
        self._directory = directory

    @property
    def directory(self) -> Path:
        self._directory.mkdir(parents=True, exist_ok=True)
        return self._directory

    def path(self, filename: str) -> Path:
        return self.directory / filename


def make_checkout(path: Path) -> None:
    common = path / "common"
    common.mkdir(parents=True)
    (common / "vrnetlab.py").write_text("# marker\n", encoding="utf-8")


class EnsureCheckoutTest(unittest.TestCase):
    @patch("engulf_clab_ensure_vrnetlab.checkout._run")
    def test_valid_environment_checkout_takes_precedence(self, run: Mock) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            configured = root / "external"
            make_checkout(configured)
            state = FilesystemState(root / "state")

            resolved = ensure_checkout(state, {"VRNETLAB_DIR": str(configured)})

            self.assertEqual(resolved, configured.resolve())
            self.assertFalse((root / "state").exists())
            run.assert_not_called()

    @patch("engulf_clab_ensure_vrnetlab.checkout._run")
    def test_invalid_environment_falls_back_to_managed_checkout(self, run: Mock) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            managed = root / "state" / "vrnetlab"
            make_checkout(managed)

            resolved = ensure_checkout(
                FilesystemState(root / "state"),
                {"VRNETLAB_DIR": str(root / "missing")},
            )

            self.assertEqual(resolved, managed.resolve())
            run.assert_not_called()

    def test_existing_invalid_managed_checkout_is_not_overwritten(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            managed = root / "state" / "vrnetlab"
            managed.mkdir(parents=True)

            with self.assertRaisesRegex(EnsureVrnetlabError, "exists but is invalid"):
                ensure_checkout(FilesystemState(root / "state"), {})

    @patch("engulf_clab_ensure_checkout.checkout.shutil.which", return_value="/usr/bin/git")
    @patch("engulf_clab_ensure_vrnetlab.checkout._run")
    def test_clone_is_staged_then_installed(self, run: Mock, _which: Mock) -> None:
        def clone(argv: list[str]) -> None:
            make_checkout(Path(argv[-1]))

        run.side_effect = clone
        with TemporaryDirectory() as directory:
            root = Path(directory)
            state_dir = root / "state"

            resolved = ensure_checkout(
                FilesystemState(state_dir),
                {"VRNETLAB_REPO": "https://example.test/vrnetlab.git"},
            )

            self.assertEqual(resolved, (state_dir / "vrnetlab").resolve())
            self.assertTrue((resolved / "common" / "vrnetlab.py").is_file())
            self.assertEqual(
                run.call_args.args[0][0:4],
                ["git", "clone", "--", "https://example.test/vrnetlab.git"],
            )
            self.assertEqual(list(state_dir.glob(".vrnetlab-clone-*")), [])

    @patch("engulf_clab_ensure_checkout.checkout.shutil.which", return_value="/usr/bin/git")
    @patch("engulf_clab_ensure_vrnetlab.checkout._run")
    def test_invalid_clone_does_not_install_target(self, _run: Mock, _which: Mock) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            state_dir = root / "state"

            with self.assertRaisesRegex(EnsureVrnetlabError, "downloaded.*invalid"):
                ensure_checkout(FilesystemState(state_dir), {})

            self.assertFalse((state_dir / "vrnetlab").exists())

    @patch("engulf_clab_ensure_checkout.checkout.shutil.which", return_value=None)
    def test_missing_git_fails_without_creating_checkout(self, _which: Mock) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(EnsureVrnetlabError, "missing required command: git"):
                ensure_checkout(FilesystemState(root / "state"), {})


if __name__ == "__main__":
    unittest.main()
