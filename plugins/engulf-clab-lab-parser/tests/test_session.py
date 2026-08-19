from __future__ import annotations
import unittest
from contextlib import chdir
from pathlib import Path
from tempfile import TemporaryDirectory
from engulf_clab_lab_parser.session import TopologySession, topology_path_from_args
class SessionTest(unittest.TestCase):
    def test_delete_overrides_nested_changes_and_additions_follow_modify(self) -> None:
        session = TopologySession(Path("lab.yml"), {"topology": {"nodes": {"a": {"x": 1}, "gone": {}}}})
        editor = session.editor("test")
        editor.modify(("topology", "nodes", "a"), {"base": True})
        editor.add(("topology", "nodes", "a", "image"), "example/a")
        editor.delete(("topology", "nodes", "gone"))
        editor.modify(("topology", "nodes", "gone", "x"), 2)
        data = session.materialize()
        self.assertEqual(data["topology"]["nodes"]["a"], {"base": True, "image": "example/a"})
        self.assertNotIn("gone", data["topology"]["nodes"])

    def test_glob_fallback_ignores_writer_temp_files(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "lab.clab.yml").write_text("topology: {}\n", encoding="utf-8")
            # A leftover temp file from a killed deploy must be ignored.
            (root / ".engulf-clab-lab-deadbeef.clab.yml").write_text(
                "topology: {}\n", encoding="utf-8"
            )
            with chdir(root):
                resolved = topology_path_from_args(())
            self.assertEqual(resolved, (root / "lab.clab.yml").resolve())
