from __future__ import annotations
import unittest
from pathlib import Path
from engulf_clab_lab_parser.session import TopologySession

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
