from __future__ import annotations

import unittest
from contextlib import chdir
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

import yaml
from engulf_api import InvocationAPI
from engulf_clab_lab_parser import TopologySession
from engulf_executable_wrapper_api import (
    AfterCallEvent,
    BeforeCallEvent,
    CallMode,
    CallOutcome,
    OutcomeKind,
    PreparedCallEvent,
)

from engulf_clab_lab_writer.plugin import TopologyCollectorPlugin


class TopologyCollectorPluginTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
