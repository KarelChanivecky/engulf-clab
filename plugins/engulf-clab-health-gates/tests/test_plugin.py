from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from engulf_api import InvocationAPI
from engulf_clab_lab_parser import TopologySession
from engulf_executable_wrapper_api import AfterCallEvent, CallMode, CallOutcome, OutcomeKind

from engulf_clab_health_gates.plugin import HealthGatesPlugin


def deployed() -> AfterCallEvent:
    return AfterCallEvent(
        binary="containerlab",
        wrapper_args=("deploy", "-t", "lab.clab.yml"),
        effective_args=("deploy", "-t", "lab.clab.yml"),
        mode=CallMode.NORMAL,
        outcome=CallOutcome(OutcomeKind.COMPLETED, 0, process_started=True),
        duration_seconds=0.1,
    )


class HealthGatesPluginTest(unittest.TestCase):
    @patch("engulf_clab_health_gates.plugin.wait_for_gates")
    def test_waits_only_after_successful_deploy(self, wait: Mock) -> None:
        api = Mock(spec=InvocationAPI)
        api.require_context.return_value = TopologySession(
            Path("lab.clab.yml"),
            {
                "topology": {"nodes": {"router": {}}},
                "x-engulf-clab-health-gates": {"nodes": ["router"]},
            },
        )
        HealthGatesPlugin().after_call(deployed(), api)
        self.assertEqual(len(wait.call_args.args[0]), 1)
        self.assertIs(wait.call_args.kwargs["info"], api.logger.info)

    @patch("engulf_clab_health_gates.plugin.wait_for_gates")
    def test_skips_failed_deploy(self, wait: Mock) -> None:
        event = AfterCallEvent(
            binary="containerlab", wrapper_args=("deploy",), effective_args=("deploy",),
            mode=CallMode.NORMAL,
            outcome=CallOutcome(OutcomeKind.COMPLETED, 1, process_started=True), duration_seconds=0.1,
        )
        HealthGatesPlugin().after_call(event, Mock(spec=InvocationAPI))
        wait.assert_not_called()
