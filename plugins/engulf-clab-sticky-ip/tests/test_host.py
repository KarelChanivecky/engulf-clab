from __future__ import annotations

import ipaddress
import unittest
from pathlib import Path
from unittest.mock import Mock

from engulf_clab_sticky_ip.errors import HostCheckError
from engulf_clab_sticky_ip.host import (
    HostInventory,
    ObservedNetwork,
    ObservedRoute,
    Owner,
    probe_candidate,
)
from engulf_clab_sticky_ip.probes import TraceStrategy


class HostTest(unittest.TestCase):
    def test_probe_uses_two_bounded_traces_and_detects_response(self) -> None:
        subnet = ipaddress.ip_network("10.20.0.0/24")
        strategy = Mock(spec=TraceStrategy)
        trace = strategy.trace
        trace.side_effect = ((ipaddress.ip_address("10.20.0.2"),), ())
        self.assertTrue(probe_candidate(subnet, timeout=0.05, strategy=strategy))

        self.assertEqual(trace.call_count, 2)
        self.assertEqual({call.args[1] for call in trace.call_args_list}, {0.05})
        self.assertEqual(
            {str(call.args[0]) for call in trace.call_args_list},
            {"10.20.0.2", "10.20.0.129"},
        )

    def test_probe_rejects_router_inside_candidate_for_both_families(self) -> None:
        for subnet, router in (("10.20.0.0/24", "10.20.0.1"), ("fd00::/120", "fd00::1")):
            with self.subTest(subnet=subnet):
                strategy = Mock(spec=TraceStrategy)
                strategy.trace.return_value = (ipaddress.ip_address(router),)
                self.assertTrue(probe_candidate(ipaddress.ip_network(subnet), strategy=strategy))

    def test_probe_allows_own_addresses_and_ignores_outside_routers(self) -> None:
        own = ipaddress.ip_address("10.20.0.2")
        strategy = Mock(spec=TraceStrategy)
        strategy.trace.return_value = (ipaddress.ip_address("192.168.1.1"), own)
        self.assertFalse(
            probe_candidate(
                ipaddress.ip_network("10.20.0.0/24"), own_addresses=(own,), strategy=strategy
            )
        )

    def test_probe_failure_is_not_treated_as_silence(self) -> None:
        strategy = Mock(spec=TraceStrategy)
        strategy.trace.side_effect = HostCheckError("probe failed")
        with self.assertRaisesRegex(HostCheckError, "probe failed"):
            probe_candidate(ipaddress.ip_network("10.20.0.0/24"), strategy=strategy)

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
