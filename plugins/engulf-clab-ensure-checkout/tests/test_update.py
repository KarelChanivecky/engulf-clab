from __future__ import annotations

import subprocess
import unittest
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory

from engulf_clab_ensure_checkout import UpdateConfig, update_checkout


class FilesystemState:
    def __init__(self, directory: Path) -> None:
        self._directory = directory

    @property
    def directory(self) -> Path:
        self._directory.mkdir(parents=True, exist_ok=True)
        return self._directory

    def exists(self, filename: str) -> bool:
        return (self.directory / filename).exists()

    def read_text(self, filename: str, **_kwargs: object) -> str:
        return (self.directory / filename).read_text(encoding="utf-8")

    def write_text(self, filename: str, data: str, **_kwargs: object) -> None:
        (self.directory / filename).write_text(data, encoding="utf-8")

    def transaction(self, **_kwargs: object):  # type: ignore[no-untyped-def]
        return nullcontext(self)


CONFIG = UpdateConfig("fixture", "FIXTURE_UPDATE", "FIXTURE_VERSION")


def git(path: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(path), *args], check=True, text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()


class CheckoutUpdateTest(unittest.TestCase):
    def test_non_git_directory_is_ignored(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertFalse(update_checkout(
                FilesystemState(root / "state"), root, {"FIXTURE_UPDATE": "1"},
                config=CONFIG, info=lambda _message: None,
            ))

    def test_clamp_and_daily_throttle(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / "remote.git"
            checkout = root / "checkout"
            subprocess.run(["git", "init", "--bare", str(remote)], check=True)
            subprocess.run(["git", "clone", str(remote), str(checkout)], check=True)
            git(checkout, "config", "user.email", "test@example.test")
            git(checkout, "config", "user.name", "Test")
            (checkout / "version").write_text("one", encoding="utf-8")
            git(checkout, "add", "version")
            git(checkout, "commit", "-m", "one")
            git(checkout, "tag", "v1.0.0")
            git(checkout, "push", "--tags", "origin", "HEAD:master")
            (checkout / "version").write_text("two", encoding="utf-8")
            git(checkout, "commit", "-am", "two")
            git(checkout, "push", "origin", "HEAD:master")
            state = FilesystemState(root / "state")

            self.assertTrue(update_checkout(
                state, checkout, {"FIXTURE_VERSION": "v1.0.0"}, config=CONFIG,
                info=lambda _message: None, now=1_000_000,
            ))
            self.assertEqual(git(checkout, "describe", "--tags", "--exact-match"), "v1.0.0")
            self.assertFalse(update_checkout(
                state, checkout, {"FIXTURE_VERSION": "v1.0.0"}, config=CONFIG,
                info=lambda _message: None, now=1_000_001,
            ))
