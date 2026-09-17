from __future__ import annotations

import ipaddress
import unittest

from engulf_clab_sticky_ip.allocation import (
    Family,
    StickyIPError,
    allocation_prefix,
    allocation_units,
    assign_node_ips,
    find_available_network,
    parse_config,
    topology_request,
)


class AllocationTest(unittest.TestCase):
    def test_kind_inherited_from_defaults_skips_non_management_modes(self) -> None:
        for mode in ("host", "none", "container:other"):
            with self.subTest(mode=mode):
                document = {"name": "demo", "topology": {
                    "defaults": {"kind": "linux"},
                    "kinds": {"linux": {"network-mode": mode}},
                    "nodes": {"unattached": {}, "attached": {"network-mode": "bridge"}},
                }}
                self.assertEqual(topology_request(document, Family.IPV4).nodes, ("attached",))

    def test_logical_blocks_grow_by_powers_of_two(self) -> None:
        cases = {
            1: (1, 24, 120),
            128: (1, 24, 120),
            129: (2, 23, 119),
            256: (2, 23, 119),
            257: (4, 22, 118),
        }
        for nodes, (units, ipv4, ipv6) in cases.items():
            with self.subTest(nodes=nodes):
                self.assertEqual(allocation_units(nodes), units)
                self.assertEqual(allocation_prefix(Family.IPV4, units), ipv4)
                self.assertEqual(allocation_prefix(Family.IPV6, units), ipv6)

    def test_node_addresses_are_stable_and_fill_freed_slots(self) -> None:
        subnet = ipaddress.ip_network("10.12.0.0/24")
        first = assign_node_ips(("a", "b", "c"), subnet, {})
        second = assign_node_ips(("a", "c", "d"), subnet, first)

        self.assertEqual(first, {"a": "10.12.0.2", "b": "10.12.0.3", "c": "10.12.0.4"})
        self.assertEqual(second, {"a": "10.12.0.2", "c": "10.12.0.4", "d": "10.12.0.3"})

    def test_second_logical_block_starts_at_the_same_offset(self) -> None:
        nodes = tuple(f"node-{index:03d}" for index in range(129))
        assigned = assign_node_ips(nodes, ipaddress.ip_network("10.13.0.0/23"), {})

        self.assertEqual(assigned["node-127"], "10.13.0.129")
        self.assertEqual(assigned["node-128"], "10.13.1.2")

    def test_topology_request_ignores_nodes_outside_management_network(self) -> None:
        document = {
            "name": "lab",
            "topology": {
                "defaults": {"network-mode": "none"},
                "groups": {"attached": {"network-mode": "bridge"}},
                "nodes": {
                    "a": {"group": "attached"},
                    "b": {},
                    "c": {"network-mode": "container:a"},
                },
            },
        }

        request = topology_request(document, Family.IPV4)

        self.assertEqual(request.nodes, ("a",))
        self.assertFalse(request.explicit)

    def test_complete_explicit_family_is_preserved(self) -> None:
        request = topology_request(
            {
                "name": "lab",
                "mgmt": {
                    "network": "lab-management",
                    "ipv4-subnet": "10.44.0.0/24",
                    "ipv6-subnet": "fd00:44::/120",
                },
                "topology": {
                    "nodes": {
                        "a": {"mgmt-ipv4": "10.44.0.10", "mgmt-ipv6": "fd00:44::10"},
                        "b": {"mgmt-ipv4": "10.44.0.11", "mgmt-ipv6": "fd00:44::11"},
                    }
                },
            },
            Family.IPV4,
        )

        self.assertEqual(request.explicit_subnet, ipaddress.ip_network("10.44.0.0/24"))
        self.assertEqual(str(request.explicit_ips["a"]), "10.44.0.10")
        self.assertEqual(request.network_name, "lab-management")

    def test_partial_explicit_family_is_rejected(self) -> None:
        with self.assertRaisesRegex(StickyIPError, "every management-attached node"):
            topology_request(
                {
                    "name": "lab",
                    "mgmt": {"ipv4-subnet": "10.44.0.0/24"},
                    "topology": {
                        "nodes": {
                            "a": {"mgmt-ipv4": "10.44.0.10"},
                            "b": {},
                        }
                    },
                },
                Family.IPV4,
            )

    def test_config_rejects_public_and_wrong_sized_pools(self) -> None:
        for value in ("203.0.113.0/24", "10.0.0.0/25"):
            with self.subTest(value=value), self.assertRaises(StickyIPError):
                parse_config({"ECLAB_STICKY_IPV4_POOL": value})

    def test_available_network_skips_blocks_and_wraps_after_cursor(self) -> None:
        pool = ipaddress.ip_network("10.0.0.0/22")
        found = find_available_network(
            (pool,),
            24,
            (ipaddress.ip_network("10.0.1.0/24"),),
            cursor_address=int(ipaddress.ip_address("10.0.0.0")),
        )
        self.assertEqual(found, (ipaddress.ip_network("10.0.2.0/24"), 0))


if __name__ == "__main__":
    unittest.main()
