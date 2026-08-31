from __future__ import annotations

import unittest
from contextlib import chdir
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

import yaml
from engulf_api import InvocationAPI
from engulf_clab_lab_parser import TopologySession
from engulf_clab_lab_parser.environment import expand_environment
from engulf_clab_lab_writer.plugin import TopologyCollectorPlugin
from engulf_executable_wrapper_api import (
    AfterCallEvent,
    BeforeCallEvent,
    CallMode,
    CallOutcome,
    OutcomeKind,
    PreparedCallEvent,
)


class TopologyCollectorPluginTest(unittest.TestCase):
    def test_generated_topology_is_stable_through_containerlab_environment_pass(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "lab.clab.yml"
            source.write_text("topology: {}\n", encoding="utf-8")
            document = {
                "topology": {
                    "nodes": {
                        "app": {
                            "image": "$FGT_IMAGE",
                            "env": {"PASSWORD": "cost$5", "KEY$": "value$OTHER"},
                        }
                    }
                }
            }
            target = root / ".engulf-clab-lab-rendered.clab.yml"
            api = Mock(spec=InvocationAPI)
            api.require_context.return_value = TopologySession(source, document)
            event = PreparedCallEvent(
                "containerlab",
                ("deploy",),
                ("deploy", "-t", str(target)),
                CallMode.NORMAL,
            )

            TopologyCollectorPlugin().prepare_call(event, api)
            generated = target.read_text(encoding="utf-8")
            after_containerlab = yaml.safe_load(
                expand_environment(
                    generated,
                    {"FGT_IMAGE": "should-not-expand", "OTHER": "wrong"},
                )
            )

        self.assertIn("$$FGT_IMAGE", generated)
        self.assertEqual(after_containerlab, document)

    def test_generated_topology_preserves_source_directory(self) -> None:
        with TemporaryDirectory() as directory:
            lab_directory = Path(directory) / "lab"
            lab_directory.mkdir()
            topology = lab_directory / "lab.clab.yml"
            document = {
                "topology": {
                    "nodes": {
                        "ldap": {
                            "binds": ["configs/ldap_start.sh:/ldap_start.sh"]
                        }
                    }
                }
            }
            topology.write_text(yaml.safe_dump(document), encoding="utf-8")

            plugin = TopologyCollectorPlugin()
            wrapper_args = ("deploy",)
            with chdir(lab_directory):
                contribution = plugin.analyze_call(
                    BeforeCallEvent("containerlab", wrapper_args, CallMode.NORMAL),
                    Mock(spec=InvocationAPI),
                )

            self.assertIsNotNone(contribution)
            assert contribution is not None
            target = Path(contribution.additions[0].args[1])
            self.assertEqual(target.parent, topology.parent)
            self.assertFalse(target.exists())

            api = Mock(spec=InvocationAPI)
            api.require_context.return_value = TopologySession(topology, document)
            effective_args = ("deploy", "-t", str(target))
            plugin.prepare_call(
                PreparedCallEvent(
                    "containerlab", wrapper_args, effective_args, CallMode.NORMAL
                ),
                api,
            )

            generated = yaml.safe_load(target.read_text(encoding="utf-8"))
            self.assertEqual(
                generated["topology"]["nodes"]["ldap"]["binds"],
                ["configs/ldap_start.sh:/ldap_start.sh"],
            )

            plugin.after_call(
                AfterCallEvent(
                    "containerlab",
                    wrapper_args,
                    effective_args,
                    CallMode.NORMAL,
                    CallOutcome(OutcomeKind.COMPLETED, 0, process_started=True),
                    0.1,
                ),
                api,
            )
            self.assertFalse(target.exists())

    def test_prepare_call_sweeps_stale_temp_topologies(self) -> None:
        with TemporaryDirectory() as directory:
            lab_directory = Path(directory) / "lab"
            lab_directory.mkdir()
            topology = lab_directory / "lab.clab.yml"
            document = {"topology": {"nodes": {"a": {"x": 1}}}}
            topology.write_text(yaml.safe_dump(document), encoding="utf-8")

            # A stale temp file from a prior killed deploy sits beside the source.
            stale = lab_directory / ".engulf-clab-lab-deadbeef.clab.yml"
            stale.write_text("topology: {}\n", encoding="utf-8")

            plugin = TopologyCollectorPlugin()
            wrapper_args = ("deploy",)
            with chdir(lab_directory):
                contribution = plugin.analyze_call(
                    BeforeCallEvent("containerlab", wrapper_args, CallMode.NORMAL),
                    Mock(spec=InvocationAPI),
                )
            assert contribution is not None
            target = Path(contribution.additions[0].args[1])

            api = Mock(spec=InvocationAPI)
            api.require_context.return_value = TopologySession(topology, document)
            effective_args = ("deploy", "-t", str(target))

            self.assertTrue(stale.exists())
            plugin.prepare_call(
                PreparedCallEvent(
                    "containerlab", wrapper_args, effective_args, CallMode.NORMAL
                ),
                api,
            )
            # The stale temp file must be gone, the fresh target must exist.
            self.assertFalse(stale.exists())
            self.assertTrue(target.exists())

            plugin.after_call(
                AfterCallEvent(
                    "containerlab",
                    wrapper_args,
                    effective_args,
                    CallMode.NORMAL,
                    CallOutcome(OutcomeKind.COMPLETED, 0, process_started=True),
                    0.1,
                ),
                api,
            )
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
