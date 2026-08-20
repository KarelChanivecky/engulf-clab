from __future__ import annotations

import unittest
from contextlib import chdir
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from engulf_api import InvocationAPI
from engulf_executable_wrapper_api import BeforeCallEvent, CallMode

from engulf_clab_lab_parser.plugin import TopologyPlugin


class TopologyPluginTest(unittest.TestCase):
    def test_destroy_selects_source_while_ignoring_writer_residue(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            topology = root / "lab.clab.yml"
            topology.write_text("topology: {}\n", encoding="utf-8")
            (root / ".engulf-clab-lab-deadbeef.clab.yml").write_text(
                "topology: {}\n", encoding="utf-8"
            )

            with chdir(root):
                contribution = TopologyPlugin().analyze_call(
                    BeforeCallEvent("containerlab", ("destroy",), CallMode.NORMAL),
                    Mock(spec=InvocationAPI),
                )

        self.assertIsNotNone(contribution)
        assert contribution is not None
        self.assertEqual(contribution.additions[0].args, ("-t", str(topology)))

    def test_destroy_preserves_explicit_topology_or_name_selection(self) -> None:
        plugin = TopologyPlugin()
        api = Mock(spec=InvocationAPI)

        for args in (
            ("destroy", "-t", "lab.clab.yml"),
            ("destroy", "--topo=lab.clab.yml"),
            ("destroy", "--topology", "lab.clab.yml"),
            ("destroy", "--name", "lab"),
            ("destroy", "--name=lab"),
        ):
            with self.subTest(args=args):
                self.assertIsNone(
                    plugin.analyze_call(
                        BeforeCallEvent("containerlab", args, CallMode.NORMAL), api
                    )
                )

    def test_destroy_preserves_native_diagnostics_without_one_source(self) -> None:
        plugin = TopologyPlugin()
        api = Mock(spec=InvocationAPI)

        with TemporaryDirectory() as directory, chdir(directory):
            self.assertIsNone(
                plugin.analyze_call(
                    BeforeCallEvent("containerlab", ("destroy",), CallMode.NORMAL),
                    api,
                )
            )
            Path("one.clab.yml").write_text("topology: {}\n", encoding="utf-8")
            Path("two.clab.yml").write_text("topology: {}\n", encoding="utf-8")
            self.assertIsNone(
                plugin.analyze_call(
                    BeforeCallEvent("containerlab", ("destroy",), CallMode.NORMAL),
                    api,
                )
            )


if __name__ == "__main__":
    unittest.main()
