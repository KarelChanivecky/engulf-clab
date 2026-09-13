from __future__ import annotations

import ipaddress
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from engulf_clab_sticky_ip.host import (
    HostCheckError,
    HostInventory,
    ObservedNetwork,
    ObservedRoute,
    Owner,
    _trace,
    probe_candidate,
)


class HostTest(unittest.TestCase):
    def test_trace_kills_the_process_at_the_deadline(self) -> None:
        process = Mock()
        process.communicate.side_effect = (
            subprocess.TimeoutExpired("traceroute", 0.05),
            ("", ""),
        )
        process.returncode = -9
        with patch("engulf_clab_sticky_ip.host.subprocess.Popen", return_value=process):
            self.assertEqual(_trace(ipaddress.ip_address("10.10.0.2"), 0.05), "")

        process.kill.assert_called_once_with()
        self.assertEqual(process.communicate.call_args_list[0].kwargs, {"timeout": 0.05})
        self.assertEqual(process.communicate.call_args_list[1].kwargs, {"timeout": 0.05})

    def test_trace_pipe_cleanup_has_a_second_deadline(self) -> None:
        process = Mock()
        process.communicate.side_effect = subprocess.TimeoutExpired("traceroute", 0.05)
        with patch("engulf_clab_sticky_ip.host.subprocess.Popen", return_value=process):
            self.assertEqual(_trace(ipaddress.ip_address("10.10.0.2"), 0.05), "")

        process.kill.assert_called_once_with()
        self.assertEqual(process.communicate.call_count, 2)
        process.stdout.close.assert_called_once_with()
        process.stderr.close.assert_called_once_with()

    def test_probe_uses_two_bounded_traces_and_detects_response(self) -> None:
        subnet = ipaddress.ip_network("10.20.0.0/24")
        with patch(
            "engulf_clab_sticky_ip.host._trace",
            side_effect=("1  10.20.0.2  0.03 ms\n", "1  *\n"),
        ) as trace:
            self.assertTrue(probe_candidate(subnet, timeout=0.05))

        self.assertEqual(trace.call_count, 2)
        self.assertEqual({call.args[1] for call in trace.call_args_list}, {0.05})

    def test_unowned_docker_and_route_overlap_are_rejected(self) -> None:
        subnet = ipaddress.ip_network("10.30.0.0/24")
        inventory = HostInventory(
            (
                ObservedNetwork(
                    "id",
                    "foreign",
                    (subnet,),
                    (),
                    {},
                    "br-foreign",
                ),
            ),
            (ObservedRoute(ipaddress.ip_network("10.40.0.0/24"), "eth0"),),
        )

        with self.assertRaises(HostCheckError):
            inventory.validate_candidate(
                subnet,
                network_name="mine",
                lab_name="lab",
                workspace=Path("/tmp/lab"),
                owned_names=set(),
                destructive=False,
            )

    def test_exact_lab_network_allows_its_addresses_and_bridge_route(self) -> None:
        workspace = Path("/tmp/lab").resolve()
        subnet = ipaddress.ip_network("10.50.0.0/24")
        endpoint = ipaddress.ip_address("10.50.0.2")
        network = ObservedNetwork(
            "id",
            "mine",
            (subnet,),
            (ipaddress.ip_address("10.50.0.1"),),
            {endpoint: Owner("lab", workspace)},
            "br-mine",
        )
        inventory = HostInventory(
            (network,),
            (ObservedRoute(subnet, "br-mine"),),
        )

        own = inventory.validate_candidate(
            subnet,
            network_name="mine",
            lab_name="lab",
            workspace=workspace,
            owned_names={"mine"},
            destructive=False,
        )

        self.assertEqual(
            own,
            frozenset({endpoint, ipaddress.ip_address("10.50.0.1")}),
        )


if __name__ == "__main__":
    unittest.main()
