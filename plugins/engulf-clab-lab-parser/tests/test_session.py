from __future__ import annotations

import unittest
from contextlib import chdir
from pathlib import Path
from tempfile import TemporaryDirectory

from engulf_clab_lab_parser.session import (
    TopologyError,
    TopologySession,
    load_topology,
    topology_path_from_args,
)


class SessionTest(unittest.TestCase):
    def test_load_topology_expands_containerlab_environment_syntax(self) -> None:
        with TemporaryDirectory() as directory:
            topology = Path(directory) / "lab.clab.yml"
            topology.write_text(
                "topology:\n"
                "  nodes:\n"
                "    fgt:\n"
                "      image: ${FGT_IMAGE:=fgt:8.0.1.0203}\n"
                "      env:\n"
                "        DEFAULT_IMAGE: ${MISSING:-$FALLBACK}\n"
                "        EMPTY_WITHOUT_COLON: ${EMPTY-fallback}\n"
                "        EMPTY_WITH_COLON: ${EMPTY:-fallback}\n"
                "        SET_ALTERNATIVE: ${SET:+alternative}\n"
                "        UNSET_ALTERNATIVE: ${MISSING+alternative}\n"
                "        UNRESOLVED: ${MISSING}\n"
                "        ESCAPED: $$FGT_IMAGE\n"
                "        POSITIONAL: $1-not-a-variable\n"
                "        YAML_BOOLEAN: ${BOOLEAN:=true}\n",
                encoding="utf-8",
            )

            document = load_topology(
                topology,
                {
                    "FGT_IMAGE": "fgt:custom",
                    "FALLBACK": "fgt:fallback",
                    "EMPTY": "",
                    "SET": "value",
                },
            )

        node = document["topology"]["nodes"]["fgt"]
        self.assertEqual(node["image"], "fgt:custom")
        self.assertEqual(
            node["env"],
            {
                "DEFAULT_IMAGE": "fgt:fallback",
                "EMPTY_WITHOUT_COLON": "$EMPTY",
                "EMPTY_WITH_COLON": "fallback",
                "SET_ALTERNATIVE": "alternative",
                "UNSET_ALTERNATIVE": None,
                "UNRESOLVED": "$MISSING",
                "ESCAPED": "$FGT_IMAGE",
                "POSITIONAL": "$1-not-a-variable",
                "YAML_BOOLEAN": True,
            },
        )

    def test_load_topology_uses_default_for_unset_image_and_rejects_unclosed_brace(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            topology = Path(directory) / "lab.clab.yml"
            topology.write_text(
                "topology:\n"
                "  nodes:\n"
                "    fgt:\n"
                "      image: ${FGT_IMAGE:=fgt:8.0.1.0203}\n",
                encoding="utf-8",
            )
            self.assertEqual(
                load_topology(topology, {})["topology"]["nodes"]["fgt"]["image"],
                "fgt:8.0.1.0203",
            )

            topology.write_text("value: ${UNCLOSED\n", encoding="utf-8")
            with self.assertRaisesRegex(TopologyError, "closing brace expected"):
                load_topology(topology, {})

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
