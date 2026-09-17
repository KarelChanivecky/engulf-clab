from __future__ import annotations

import unittest
from contextlib import chdir
from pathlib import Path
from tempfile import TemporaryDirectory

from engulf_clab_lab_parser.environment import (
    EnvFileError,
    env_file_for_topology,
    parse_env_file,
)
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
                "UNSET_ALTERNATIVE": "",
                "UNRESOLVED": "$MISSING",
                "ESCAPED": "$FGT_IMAGE",
                "POSITIONAL": "$1-not-a-variable",
                "YAML_BOOLEAN": "true",
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


class EnvFileTest(unittest.TestCase):
    _TOPOLOGY = (
        "name: eclab-all-features\n"
        "topology:\n"
        "  nodes:\n"
        "    fgt:\n"
        "      image: $FGT_IMAGE\n"
        "      license: $POOL\n"
    )

    def _lab(self, directory: str, name: str = "all-features.clab.yml") -> Path:
        topology = Path(directory) / name
        topology.write_text(self._TOPOLOGY, encoding="utf-8")
        return topology

    def test_sibling_env_file_resolves_topology_variables(self) -> None:
        with TemporaryDirectory() as directory:
            topology = self._lab(directory)
            # Named for the file, not the `name:` field, which differs here.
            (Path(directory) / "all-features.env").write_text(
                "# lab-private\nexport FGT_IMAGE=fgt:8.0.1\nPOOL='/pools/fgt'\n",
                encoding="utf-8",
            )

            nodes = load_topology(topology, {})["topology"]["nodes"]

            self.assertEqual(nodes["fgt"]["image"], "fgt:8.0.1")
            self.assertEqual(nodes["fgt"]["license"], "/pools/fgt")

    def test_env_file_values_do_not_become_node_environment(self) -> None:
        with TemporaryDirectory() as directory:
            topology = self._lab(directory)
            (Path(directory) / "all-features.env").write_text(
                "FGT_IMAGE=fgt:8.0.1\nPOOL=/pools/fgt\nSECRET=hunter2\n", encoding="utf-8"
            )

            node = load_topology(topology, {})["topology"]["nodes"]["fgt"]

            # The file resolves the document; it never becomes container env.
            self.assertNotIn("env", node)

    def test_process_environment_overrides_the_env_file(self) -> None:
        with TemporaryDirectory() as directory:
            topology = self._lab(directory)
            (Path(directory) / "all-features.env").write_text(
                "FGT_IMAGE=fgt:8.0.1\nPOOL=/pools/fgt\n", encoding="utf-8"
            )

            nodes = load_topology(topology, {"FGT_IMAGE": "fgt:override"})["topology"]["nodes"]

            self.assertEqual(nodes["fgt"]["image"], "fgt:override")
            self.assertEqual(nodes["fgt"]["license"], "/pools/fgt")

    def test_absent_sibling_env_file_is_not_an_error(self) -> None:
        with TemporaryDirectory() as directory:
            topology = self._lab(directory)

            nodes = load_topology(topology, {})["topology"]["nodes"]

            # Unset variables stay literal, exactly as without the convention.
            self.assertEqual(nodes["fgt"]["image"], "$FGT_IMAGE")

    def test_override_replaces_the_convention_and_must_exist(self) -> None:
        with TemporaryDirectory() as directory:
            topology = self._lab(directory)
            (Path(directory) / "all-features.env").write_text(
                "FGT_IMAGE=fgt:convention\nPOOL=/pools/fgt\n", encoding="utf-8"
            )
            explicit = Path(directory) / "shared.env"
            explicit.write_text("FGT_IMAGE=fgt:explicit\n", encoding="utf-8")

            nodes = load_topology(topology, {"ECLAB_ENV_FILE": str(explicit)})["topology"]["nodes"]
            self.assertEqual(nodes["fgt"]["image"], "fgt:explicit")
            # The convention is replaced, not merged, so POOL is unresolved.
            self.assertEqual(nodes["fgt"]["license"], "$POOL")

            missing = Path(directory) / "absent.env"
            with self.assertRaises(TopologyError) as raised:
                load_topology(topology, {"ECLAB_ENV_FILE": str(missing)})
            self.assertIn("does not exist", str(raised.exception))

    def test_malformed_env_file_names_the_file_and_line(self) -> None:
        with TemporaryDirectory() as directory:
            topology = self._lab(directory)
            (Path(directory) / "all-features.env").write_text(
                "FGT_IMAGE=fgt:8.0.1\nnot an assignment\n", encoding="utf-8"
            )

            with self.assertRaises(TopologyError) as raised:
                load_topology(topology, {})

            message = str(raised.exception)
            self.assertIn("all-features.env", message)
            self.assertIn("line 2", message)


class EnvFileNameTest(unittest.TestCase):
    def test_stem_drops_the_full_topology_suffix(self) -> None:
        for name, expected in (
            ("all-features.clab.yml", "all-features.env"),
            ("all-features.clab.yaml", "all-features.env"),
            ("clab.yml", "clab.env"),
            ("topology.yaml", "topology.env"),
        ):
            with self.subTest(name=name):
                self.assertEqual(env_file_for_topology(Path("/labs") / name).name, expected)


class EnvFileParseTest(unittest.TestCase):
    def test_accepted_value_forms(self) -> None:
        values = parse_env_file(
            "# comment\n"
            "\n"
            "export EXPORTED=1\n"
            "SINGLE='literal $NOPE'\n"
            'DOUBLE="line\\nbreak"\n'
            "BARE=value # trailing\n"
            "HASH=api#1\n"
        )

        self.assertEqual(
            values,
            {
                "EXPORTED": "1",
                "SINGLE": "literal $NOPE",
                "DOUBLE": "line\nbreak",
                "BARE": "value",
                "HASH": "api#1",
            },
        )

    def test_unterminated_quote_is_rejected(self) -> None:
        with self.assertRaises(EnvFileError):
            parse_env_file('BROKEN="unterminated\n')
