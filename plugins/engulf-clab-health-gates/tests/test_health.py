from __future__ import annotations

import unittest
from pathlib import Path

from engulf_clab_health_gates.health import HealthGateError, gates_from_topology, wait_for_gates


class HealthConfigTest(unittest.TestCase):
    def test_defaults_to_all_topology_nodes(self) -> None:
        gates = gates_from_topology(
            {
                "name": "demo",
                "topology": {"nodes": {"router": {}, "client": {}}},
                "x-engulf-clab-health-gates": {"timeout": 30},
            },
            Path("lab.clab.yml"),
        )
        self.assertEqual(
            [(gate.node, gate.container) for gate in gates],
            [("router", "clab-demo-router"), ("client", "clab-demo-client")],
        )

    def test_retries_until_node_is_running_and_healthy(self) -> None:
        gates = gates_from_topology(
            {
                "name": "demo",
                "topology": {"nodes": {"router": {}}},
                "x-engulf-clab-health-gates": {
                    "nodes": ["router"], "timeout": 2, "interval": 1,
                },
            },
            Path("lab.clab.yml"),
        )
        clock = [0.0]
        states = iter([("created", None), ("running", "starting"), ("running", "healthy")])

        wait_for_gates(
            gates,
            info=lambda _message: None,
            now=lambda: clock[0],
            sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
            inspect=lambda _container: next(states),
        )

    def test_running_container_without_health_status_does_not_pass(self) -> None:
        gates = gates_from_topology(
            {
                "name": "demo",
                "topology": {"nodes": {"router": {}}},
                "x-engulf-clab-health-gates": {
                    "nodes": ["router"], "timeout": 1, "interval": 1,
                },
            },
            Path("lab.clab.yml"),
        )
        clock = [0.0]

        with self.assertRaisesRegex(
            HealthGateError, "container has no Docker HEALTHCHECK status"
        ):
            wait_for_gates(
                gates,
                info=lambda _message: None,
                now=lambda: clock[0],
                sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
                inspect=lambda _container: ("running", None),
            )

    def test_reports_node_timeout(self) -> None:
        gates = gates_from_topology(
            {
                "topology": {"nodes": {"router": {}}},
                "x-engulf-clab-health-gates": {"timeout": 1, "interval": 1},
            },
            Path("lab.clab.yml"),
        )
        clock = [0.0]
        with self.assertRaisesRegex(HealthGateError, "did not become running and healthy"):
            wait_for_gates(
                gates,
                info=lambda _message: None,
                now=lambda: clock[0],
                sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
                inspect=lambda _container: ("exited", None),
            )
