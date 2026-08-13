from __future__ import annotations

import json
import tarfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from engulf_clab_freeze.command import freeze
from engulf_clab_freeze.state import STATE_FILENAME, track_archive, tracked_archives


class MemoryStateStore:
    def __init__(self) -> None:
        self.content: dict[str, str] = {}

    def exists(self, filename: str) -> bool:
        return filename in self.content

    def read_text(self, filename: str) -> str:
        return self.content[filename]

    def write_text(self, filename: str, content: str) -> None:
        self.content[filename] = content

    def delete(self, filename: str, *, missing_ok: bool = False) -> None:
        if filename not in self.content and not missing_ok:
            raise FileNotFoundError(filename)
        self.content.pop(filename, None)

    @contextmanager
    def transaction(self, *, timeout: float | None = None) -> Iterator[MemoryStateStore]:
        del timeout
        yield self


class FreezeStateTest(unittest.TestCase):
    def test_missing_tracked_archive_is_removed_from_workspace_state(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "share.tar.gz"
            archive.write_bytes(b"archive")
            store = MemoryStateStore()

            track_archive(store, root, archive)
            self.assertEqual(tracked_archives(store, root), frozenset({Path("share.tar.gz")}))
            self.assertEqual(
                json.loads(store.content[STATE_FILENAME]),
                {"archives": ["share.tar.gz"], "version": 1},
            )

            archive.unlink()

            self.assertEqual(tracked_archives(store, root), frozenset())
            self.assertNotIn(STATE_FILENAME, store.content)

    def test_later_freezes_exclude_existing_tracked_archives(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "lab"
            root.mkdir()
            topology = root / "lab.clab.yml"
            topology.write_text("topology: {nodes: {router: {}}}\n", encoding="utf-8")
            store = MemoryStateStore()
            first = root / "first.tar.gz"
            second = root / "second.tar.gz"

            with patch("engulf_clab_freeze.command._download_wheels"):
                freeze(topology, first, workspace=store)  # type: ignore[arg-type]
                freeze(topology, second, workspace=store)  # type: ignore[arg-type]

            with tarfile.open(second, "r:gz") as archive:
                self.assertFalse(any(name.endswith("/first.tar.gz") for name in archive.getnames()))
                self.assertFalse(any(".eclab-freeze-" in name for name in archive.getnames()))

            first.unlink()
            self.assertEqual(tracked_archives(store, root), frozenset({Path("second.tar.gz")}))


if __name__ == "__main__":
    unittest.main()
