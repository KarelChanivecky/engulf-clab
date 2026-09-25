from __future__ import annotations

import json
import tomllib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from engulf_api import InvocationAPI
from engulf_executable_wrapper_api import BeforeCallEvent, CallMode, PreparedCallEvent

from engulf_clab_fortinet_operation_guard.plugin import (
    FortinetOperationGuardError,
    FortinetOperationGuardPlugin,
)


class FortinetOperationGuardPluginTest(unittest.TestCase):
    def test_dependencies_and_entry_points_are_declared_in_metadata(self) -> None:
        package = Path(__file__).parents[1]
        project = tomllib.loads((package / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.assertEqual(
            project["entry-points"][
                "engulf.plugins.v1.dependency.engulf_clab_fortinet_operation_guard"
            ],
            {
                "engulf_clab.lab_parser": "preprocess=before; postprocess=none",
                "engulf_clab.schema": "preprocess=after; postprocess=none",
            },
        )
        for group in (
            "engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper",
            "engulf.plugins.v1.application.engulf_clab",
        ):
            self.assertEqual(
                project["entry-points"][group],
                {
                    "engulf_clab.fortinet_operation_guard": "engulf_clab_fortinet_operation_guard:plugin"
                },
            )

    def test_fortigate_reconfigure_is_preempted(self) -> None:
        with TemporaryDirectory() as directory:
            topology = _write_topology(Path(directory), "fortinet_fortigate")
            api = Mock(spec=InvocationAPI)
            contribution = FortinetOperationGuardPlugin().analyze_call(
                BeforeCallEvent(
                    "containerlab",
                    ("deploy", "--reconfigure", "-t", str(topology)),
                    CallMode.NORMAL,
                ),
                api,
            )

        self.assertIsNotNone(contribution)
        assert contribution is not None
        self.assertEqual(contribution.preempt_exit_code, 1)
        api.logger.error.assert_called_once_with(
            "%s", "Fortinet devices currently do not support deploy --reconfigure."
        )
        api.set_context.assert_not_called()

    def test_restart_is_preempted_for_inherited_fortiproxy(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            topology = root / "lab.clab.yml"
            topology.write_text(
                "topology:\n  defaults:\n    kind: fortinet_fortiproxy\n  nodes:\n    proxy: {}\n",
                encoding="utf-8",
            )
            api = Mock(spec=InvocationAPI)
            contribution = FortinetOperationGuardPlugin().analyze_call(
                BeforeCallEvent("containerlab", ("restart", "-t", str(topology)), CallMode.NORMAL),
                api,
            )

        self.assertIsNotNone(contribution)
        assert contribution is not None
        self.assertEqual(contribution.preempt_exit_code, 1)
        api.logger.error.assert_called_once_with(
            "%s", "Fortinet devices currently do not support restart."
        )

    @patch("engulf_clab_fortinet_operation_guard.plugin.subprocess.run")
    def test_plain_deploy_is_rejected_when_matching_container_is_running(self, run: Mock) -> None:
        with TemporaryDirectory() as directory:
            topology = _write_topology(Path(directory), "fortinet_fortigate")
            api = Mock(spec=InvocationAPI)
            plugin = FortinetOperationGuardPlugin()
            contribution = plugin.analyze_call(
                BeforeCallEvent("containerlab", ("deploy", "-t", str(topology)), CallMode.NORMAL),
                api,
            )
            self.assertIsNone(contribution)
            target = api.set_context.call_args.args[1]
            api.get_context.return_value = target
            run.side_effect = [
                Mock(returncode=0, stdout="abc\n", stderr=""),
                Mock(
                    returncode=0,
                    stdout=json.dumps(
                        [
                            {
                                "Config": {
                                    "Labels": {
                                        "containerlab": "lab",
                                        "clab-topo-file": str(topology),
                                    }
                                },
                                "State": {"Running": True},
                            }
                        ]
                    ),
                    stderr="",
                ),
            ]
            event = PreparedCallEvent(
                "containerlab",
                ("deploy", "-t", str(topology)),
                ("deploy", "-t", str(topology)),
                CallMode.NORMAL,
            )

            with self.assertRaisesRegex(
                FortinetOperationGuardError,
                "Fortinet devices currently do not support deploy when the lab is already running",
            ):
                plugin.prepare_call(event, api)

        api.logger.error.assert_called_once()

    @patch("engulf_clab_fortinet_operation_guard.plugin.subprocess.run")
    def test_plain_deploy_is_allowed_when_matching_container_is_stopped(self, run: Mock) -> None:
        with TemporaryDirectory() as directory:
            topology = _write_topology(Path(directory), "fortinet_fortigate")
            api = Mock(spec=InvocationAPI)
            plugin = FortinetOperationGuardPlugin()
            plugin.analyze_call(
                BeforeCallEvent("containerlab", ("deploy", "-t", str(topology)), CallMode.NORMAL),
                api,
            )
            api.get_context.return_value = api.set_context.call_args.args[1]
            run.return_value = Mock(returncode=0, stdout="", stderr="")

            plugin.prepare_call(
                PreparedCallEvent("containerlab", ("deploy",), ("deploy",), CallMode.NORMAL),
                api,
            )

        api.logger.error.assert_not_called()

    def test_non_fortinet_topology_is_untouched(self) -> None:
        with TemporaryDirectory() as directory:
            topology = _write_topology(Path(directory), "linux")
            api = Mock(spec=InvocationAPI)
            contribution = FortinetOperationGuardPlugin().analyze_call(
                BeforeCallEvent("containerlab", ("deploy", "-t", str(topology)), CallMode.NORMAL),
                api,
            )

        self.assertIsNone(contribution)
        api.set_context.assert_not_called()


def _write_topology(root: Path, kind: str) -> Path:
    topology = root / "lab.clab.yml"
    topology.write_text(
        f"name: lab\ntopology:\n  nodes:\n    router:\n      kind: {kind}\n",
        encoding="utf-8",
    )
    return topology
