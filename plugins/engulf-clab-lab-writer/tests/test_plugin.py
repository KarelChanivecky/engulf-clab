from __future__ import annotations

import unittest
from contextlib import chdir
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

import tomllib
import yaml
from engulf_api import InvocationAPI
from engulf_clab_lab_parser import TopologySession, derived_topology_path
from engulf_clab_lab_parser.environment import expand_environment
from engulf_clab_lab_writer.plugin import TopologyCollectorPlugin
from engulf_executable_wrapper_api import (
    AfterCallEvent,
    BeforeCallEvent,
    CallMode,
    CallOutcome,
    OutcomeKind,
    PreparationFailedEvent,
    PreparedCallEvent,
)


class TopologyCollectorPluginTest(unittest.TestCase):
    def test_dependencies_are_declared_in_package_metadata(self) -> None:
        project_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
        project = tomllib.loads(project_path.read_text(encoding="utf-8"))["project"]
        group = project["entry-points"][
            "engulf.plugins.v1.dependency.engulf_clab_lab_writer"
        ]

        self.assertEqual(
            group,
            {
                "engulf_clab.lab_parser": "preprocess=before; postprocess=none",
                "engulf_clab.schema": "preprocess=after; postprocess=none",
            },
        )
        self.assertNotIn("plugin_dependencies", TopologyCollectorPlugin.__dict__)

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
                "name": "retained-lab",
                "mgmt": {
                    "network": "custom-management",
                    "ipv4-subnet": "172.31.255.0/24",
                },
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
            self.assertEqual(generated["mgmt"]["network"], "custom-management")
            self.assertEqual(generated["mgmt"]["ipv4-subnet"], "172.31.255.0/24")

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
            self.assertTrue(target.exists())

            plugin.after_call(
                AfterCallEvent(
                    "containerlab",
                    ("destroy",),
                    ("destroy", "-t", str(target)),
                    CallMode.NORMAL,
                    CallOutcome(OutcomeKind.COMPLETED, 0, process_started=True),
                    0.1,
                ),
                api,
            )
            self.assertFalse(target.exists())

    def test_stable_topology_survives_redeploy_and_failed_destroy(self) -> None:
        with TemporaryDirectory() as directory:
            lab_directory = Path(directory) / "lab"
            lab_directory.mkdir()
            topology = lab_directory / "lab.clab.yml"
            document = {"topology": {"nodes": {"a": {"x": 1}}}}
            topology.write_text(yaml.safe_dump(document), encoding="utf-8")

            plugin = TopologyCollectorPlugin()
            wrapper_args = ("deploy",)
            with chdir(lab_directory):
                contribution = plugin.analyze_call(
                    BeforeCallEvent("containerlab", wrapper_args, CallMode.NORMAL),
                    Mock(spec=InvocationAPI),
                )
            assert contribution is not None
            target = Path(contribution.additions[0].args[1])
            self.assertEqual(target, derived_topology_path(topology))

            api = Mock(spec=InvocationAPI)
            api.require_context.return_value = TopologySession(topology, document)
            effective_args = ("deploy", "-t", str(target))

            plugin.prepare_call(
                PreparedCallEvent(
                    "containerlab", wrapper_args, effective_args, CallMode.NORMAL
                ),
                api,
            )
            self.assertTrue(target.exists())

            # A redeploy rebuilds and deterministically replaces the retained path.
            api.require_context.return_value = TopologySession(
                topology, {"topology": {"nodes": {"b": {"x": 2}}}}
            )
            redeploy_args = ("redeploy", "-t", str(topology))
            redeploy_effective = ("redeploy", "-t", str(target))
            plugin.prepare_call(
                PreparedCallEvent(
                    "containerlab", redeploy_args, redeploy_effective, CallMode.NORMAL
                ),
                api,
            )
            self.assertIn("b", yaml.safe_load(target.read_text())["topology"]["nodes"])

            plugin.after_call(
                AfterCallEvent(
                    "containerlab",
                    ("destroy",),
                    ("destroy", "-t", str(target)),
                    CallMode.NORMAL,
                    CallOutcome(OutcomeKind.COMPLETED, 1, process_started=True),
                    0.1,
                ),
                api,
            )
            self.assertTrue(target.exists())

            plugin.after_call(
                AfterCallEvent(
                    "containerlab",
                    ("destroy",),
                    ("destroy", "-t", str(target)),
                    CallMode.NORMAL,
                    CallOutcome(OutcomeKind.COMPLETED, 0, process_started=True),
                    0.1,
                ),
                api,
            )
            self.assertFalse(target.exists())

    def test_later_preparation_failure_removes_new_topology(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "lab.clab.yml"
            source.write_text("topology: {}\n", encoding="utf-8")
            target = derived_topology_path(source)
            wrapper_args = ("deploy",)
            effective_args = ("deploy", "-t", str(target))
            api = Mock(spec=InvocationAPI)
            api.require_context.return_value = TopologySession(
                source, {"topology": {"nodes": {"new": {}}}}
            )
            plugin = TopologyCollectorPlugin()

            plugin.prepare_call(
                PreparedCallEvent(
                    "containerlab", wrapper_args, effective_args, CallMode.NORMAL
                ),
                api,
            )
            plugin.prepare_failed(
                PreparationFailedEvent(
                    "containerlab",
                    wrapper_args,
                    effective_args,
                    CallMode.NORMAL,
                    "later plugin failed",
                ),
                api,
            )

            self.assertFalse(target.exists())

    def test_later_preparation_failure_restores_retained_topology(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "lab.clab.yml"
            source.write_text("topology: {}\n", encoding="utf-8")
            target = derived_topology_path(source)
            previous = b"topology:\n  nodes:\n    retained: {}\n"
            target.write_bytes(previous)
            wrapper_args = ("deploy",)
            effective_args = ("deploy", "-t", str(target))
            api = Mock(spec=InvocationAPI)
            api.require_context.return_value = TopologySession(
                source, {"topology": {"nodes": {"replacement": {}}}}
            )
            plugin = TopologyCollectorPlugin()

            plugin.prepare_call(
                PreparedCallEvent(
                    "containerlab", wrapper_args, effective_args, CallMode.NORMAL
                ),
                api,
            )
            self.assertNotEqual(target.read_bytes(), previous)
            plugin.prepare_failed(
                PreparationFailedEvent(
                    "containerlab",
                    wrapper_args,
                    effective_args,
                    CallMode.NORMAL,
                    "later plugin failed",
                ),
                api,
            )

            self.assertEqual(target.read_bytes(), previous)

    def test_successful_destroy_all_removes_retained_topologies(self) -> None:
        with TemporaryDirectory() as directory, chdir(directory):
            retained = Path(".engulf-clab-lab-0123456789abcdef.clab.yml")
            retained.write_text("topology: {}\n", encoding="utf-8")

            TopologyCollectorPlugin().after_call(
                AfterCallEvent(
                    "containerlab",
                    ("destroy", "--all"),
                    ("destroy", "--all"),
                    CallMode.NORMAL,
                    CallOutcome(OutcomeKind.COMPLETED, 0, process_started=True),
                    0.1,
                ),
                Mock(spec=InvocationAPI),
            )

            self.assertFalse(retained.exists())


if __name__ == "__main__":
    unittest.main()
