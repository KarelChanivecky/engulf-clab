from __future__ import annotations

import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from engulf_clab_vrnetlab.errors import VrnetlabError
from engulf_clab_vrnetlab.state import (
    STATE_BASENAME,
    BuildFingerprint,
    load_state,
    save_state,
)
from engulf_clab_vrnetlab.vrnetlab import builder_directory, vrnetlab_root


class MemoryStateStore:
    def __init__(self) -> None:
        self.content: dict[str, str] = {}

    def exists(self, basename: str) -> bool:
        return basename in self.content

    def read_text(self, basename: str) -> str:
        return self.content[basename]

    def write_text(self, basename: str, content: str) -> None:
        self.content[basename] = content

    @contextmanager
    def transaction(self, *, timeout: float | None = None) -> Iterator[MemoryStateStore]:
        del timeout
        yield self


class StateTest(unittest.TestCase):
    def test_round_trip_uses_one_basename_content_record(self) -> None:
        store = MemoryStateStore()
        fingerprint = BuildFingerprint("abc", "router-v1.qcow2", "git:def", "vendor/router")

        save_state(store, {"vrnetlab/vendor_router:1": fingerprint})

        self.assertIn(STATE_BASENAME, store.content)
        self.assertEqual(load_state(store), {"vrnetlab/vendor_router:1": fingerprint})

    def test_missing_state_does_not_create_content(self) -> None:
        store = MemoryStateStore()
        self.assertEqual(load_state(store), {})
        self.assertEqual(store.content, {})

    def test_invalid_state_fails(self) -> None:
        store = MemoryStateStore()
        store.content[STATE_BASENAME] = "[]"
        with self.assertRaises(VrnetlabError):
            load_state(store)


class CheckoutTest(unittest.TestCase):
    def test_context_path_is_required(self) -> None:
        with TemporaryDirectory() as context_dir:
            self.assertEqual(vrnetlab_root(context_dir), Path(context_dir))
        with self.assertRaisesRegex(VrnetlabError, "does not contain"):
            vrnetlab_root(None)

    def test_builder_requires_safe_vendor_type_and_makefile(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            builder = root / "vendor" / "router"
            builder.mkdir(parents=True)
            (builder / "Makefile").write_text("all:\n\t@true\n", encoding="utf-8")

            self.assertEqual(builder_directory(root, "vendor/router"), builder)
            with self.assertRaises(VrnetlabError):
                builder_directory(root, "vendor/../router")
            with self.assertRaises(VrnetlabError):
                builder_directory(root, "/vendor/router")


if __name__ == "__main__":
    unittest.main()
