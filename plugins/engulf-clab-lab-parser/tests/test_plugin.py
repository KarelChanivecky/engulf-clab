from __future__ import annotations

import unittest
from contextlib import chdir
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from engulf_api import InvocationAPI
from engulf_clab_lab_parser.plugin import TopologyPlugin
from engulf_clab_lab_parser.session import (
    TOPOLOGY_CONTEXT,
    TopologySession,
    derived_topology_path,
)
from engulf_executable_wrapper_api import (
    BeforeCallEvent,
    CallMode,
    PreparedCallEvent,
)


class TopologyPluginTest(unittest.TestCase):
    def test_prepare_expands_from_effective_call_environment(self) -> None:
        with TemporaryDirectory() as directory:
            topology = Path(directory) / "lab.clab.yml"
            topology.write_text(
                "topology:\n"
                "  nodes:\n"
                "    fgt:\n"
                "      image: ${FGT_IMAGE:=fgt:default}\n",
                encoding="utf-8",
            )
            api = Mock(spec=InvocationAPI)

            TopologyPlugin().prepare_call(
                PreparedCallEvent(
                    "containerlab",
                    ("deploy", "-t", str(topology)),
                    ("deploy", "-t", str(topology)),
                    CallMode.NORMAL,
                    {"FGT_IMAGE": "fgt:from-event"},
                ),
                api,
            )

        api.set_context.assert_called_once()
        context_id, session = api.set_context.call_args.args
        self.assertEqual(context_id, TOPOLOGY_CONTEXT)
        self.assertIsInstance(session, TopologySession)
        self.assertEqual(
            session.original_document()["topology"]["nodes"]["fgt"]["image"],
            "fgt:from-event",
        )

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

    def test_destroy_selects_retained_topology_for_implicit_and_explicit_source(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            topology = root / "lab.clab.yml"
            topology.write_text("topology: {}\n", encoding="utf-8")
            retained = derived_topology_path(topology)
            retained.write_text("topology: {}\n", encoding="utf-8")
            plugin = TopologyPlugin()

            with chdir(root):
                implicit = plugin.analyze_call(
                    BeforeCallEvent("containerlab", ("destroy",), CallMode.NORMAL),
                    Mock(spec=InvocationAPI),
                )
                explicit = plugin.analyze_call(
                    BeforeCallEvent(
                        "containerlab",
                        ("destroy", "--topology", str(topology)),
                        CallMode.NORMAL,
                    ),
                    Mock(spec=InvocationAPI),
                )

        assert implicit is not None
        assert explicit is not None
        self.assertEqual(implicit.additions[0].args, ("-t", str(retained)))
        self.assertEqual(explicit.additions[0].args, ("-t", str(retained)))
        self.assertEqual(explicit.removals, frozenset({1, 2}))

    def test_destroy_preserves_explicit_topology_without_retained_copy_or_name(self) -> None:
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

    def test_destroy_name_selects_unique_retained_topology(self) -> None:
        with TemporaryDirectory() as directory, chdir(directory):
            root = Path(directory)
            retained = root / ".engulf-clab-lab-0123456789abcdef.clab.yml"
            retained.write_text(
                "name: selected\ntopology:\n  nodes: {}\n", encoding="utf-8"
            )

            contribution = TopologyPlugin().analyze_call(
                BeforeCallEvent(
                    "containerlab",
                    ("destroy", "--name=selected"),
                    CallMode.NORMAL,
                ),
                Mock(spec=InvocationAPI),
            )

        assert contribution is not None
        self.assertEqual(contribution.removals, frozenset({1}))
        self.assertEqual(contribution.additions[0].args, ("-t", str(retained)))

    def test_lab_commands_name_the_retained_topology_instead_of_globbing(self) -> None:
        """Containerlab refuses to glob a directory holding writer residue.

        The derived topology stays beside the source until destroy, so
        `inspect`, `graph`, and `save` see two matches for *.clab.yml and fail
        before reaching the lab.
        """
        with TemporaryDirectory() as directory:
            root = Path(directory)
            topology = root / "lab.clab.yml"
            topology.write_text("topology: {}\n", encoding="utf-8")
            retained = derived_topology_path(topology)
            retained.write_text("topology: {}\n", encoding="utf-8")
            plugin = TopologyPlugin()
            api = Mock(spec=InvocationAPI)

            with chdir(root):
                for args in (
                    ("inspect",),
                    ("inspect", "interfaces"),
                    ("graph", "--offline"),
                    ("save",),
                ):
                    with self.subTest(args=args):
                        contribution = plugin.analyze_call(
                            BeforeCallEvent("containerlab", args, CallMode.NORMAL), api
                        )

                        assert contribution is not None
                        self.assertEqual(contribution.removals, frozenset())
                        self.assertEqual(
                            contribution.additions[0].args, ("-t", str(retained))
                        )

    def test_lab_commands_fall_back_to_the_source_without_a_retained_topology(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            topology = root / "lab.clab.yml"
            topology.write_text("topology: {}\n", encoding="utf-8")

            with chdir(root):
                contribution = TopologyPlugin().analyze_call(
                    BeforeCallEvent("containerlab", ("inspect",), CallMode.NORMAL),
                    Mock(spec=InvocationAPI),
                )

        assert contribution is not None
        self.assertEqual(contribution.additions[0].args, ("-t", str(topology)))

    def test_lab_commands_route_explicit_source_to_retained_topology(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            topology = root / "lab.clab.yml"
            topology.write_text("topology: {}\n", encoding="utf-8")
            retained = derived_topology_path(topology)
            retained.write_text("topology: {}\n", encoding="utf-8")
            plugin = TopologyPlugin()
            api = Mock(spec=InvocationAPI)

            for args in (
                ("inspect", "-t", str(topology)),
                ("inspect", f"--topo={topology}"),
                ("graph", "--topology", str(topology), "--offline"),
            ):
                with self.subTest(args=args):
                    contribution = plugin.analyze_call(
                        BeforeCallEvent("containerlab", args, CallMode.NORMAL), api
                    )

                    assert contribution is not None
                    self.assertEqual(
                        contribution.additions[0].args, ("-t", str(retained))
                    )
                    self.assertTrue(contribution.removals)

    def test_lab_commands_keep_non_source_lab_selection(self) -> None:
        plugin = TopologyPlugin()
        api = Mock(spec=InvocationAPI)

        for args in (
            ("inspect", "--name", "lab"),
            ("save", "--name=lab"),
            ("inspect", "-a"),
            ("inspect", "--all"),
        ):
            with self.subTest(args=args):
                self.assertIsNone(
                    plugin.analyze_call(
                        BeforeCallEvent("containerlab", args, CallMode.NORMAL), api
                    )
                )

    def test_lab_commands_keep_explicit_source_without_retained_topology(self) -> None:
        with TemporaryDirectory() as directory:
            topology = Path(directory) / "lab.clab.yml"
            topology.write_text("topology: {}\n", encoding="utf-8")

            contribution = TopologyPlugin().analyze_call(
                BeforeCallEvent(
                    "containerlab",
                    ("inspect", "-t", str(topology)),
                    CallMode.NORMAL,
                ),
                Mock(spec=InvocationAPI),
            )

        self.assertIsNone(contribution)

    def test_lab_commands_preserve_native_diagnostics_without_one_source(self) -> None:
        plugin = TopologyPlugin()
        api = Mock(spec=InvocationAPI)

        with TemporaryDirectory() as directory, chdir(directory):
            self.assertIsNone(
                plugin.analyze_call(
                    BeforeCallEvent("containerlab", ("inspect",), CallMode.NORMAL), api
                )
            )
            Path("one.clab.yml").write_text("topology: {}\n", encoding="utf-8")
            Path("two.clab.yml").write_text("topology: {}\n", encoding="utf-8")
            self.assertIsNone(
                plugin.analyze_call(
                    BeforeCallEvent("containerlab", ("inspect",), CallMode.NORMAL), api
                )
            )

    def test_host_wide_commands_are_not_narrowed_to_one_lab(self) -> None:
        """`exec` and `events` act on every lab when no topology is named."""
        plugin = TopologyPlugin()
        api = Mock(spec=InvocationAPI)

        with TemporaryDirectory() as directory, chdir(directory):
            topology = Path("lab.clab.yml")
            topology.write_text("topology: {}\n", encoding="utf-8")
            derived_topology_path(topology).write_text(
                "topology: {}\n", encoding="utf-8"
            )

            for args in (("exec", "--cmd", "true"), ("events",), ("redeploy",)):
                with self.subTest(args=args):
                    self.assertIsNone(
                        plugin.analyze_call(
                            BeforeCallEvent("containerlab", args, CallMode.NORMAL), api
                        )
                    )

    def test_help_mode_names_no_topology(self) -> None:
        with TemporaryDirectory() as directory, chdir(directory):
            Path("lab.clab.yml").write_text("topology: {}\n", encoding="utf-8")

            self.assertIsNone(
                TopologyPlugin().analyze_call(
                    BeforeCallEvent("containerlab", ("inspect",), CallMode.HELP),
                    Mock(spec=InvocationAPI),
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
