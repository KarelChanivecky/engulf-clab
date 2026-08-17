from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from engulf_clab_wan.errors import WanError
from engulf_clab_wan.networks import (
    LABEL_PREFIX,
    WanContract,
    detect_uplink_interface,
    dhcp_wan_bridges,
    wan_contract,
)
from engulf_clab_wan.topology import load_topology, topology_path_from_args


class TopologyArgsTest(unittest.TestCase):
    def test_short_topology_option(self) -> None:
        self.assertEqual(topology_path_from_args(("-t", "lab.yml")), Path("lab.yml"))

    def test_long_topology_assignment(self) -> None:
        self.assertEqual(
            topology_path_from_args(("--topo=lab.yml",)),
            Path("lab.yml"),
        )

    def test_default_topology(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            topology = root / "lab.clab.yml"
            topology.write_text("topology: {}\n", encoding="utf-8")
            self.assertEqual(topology_path_from_args((), root), topology)

    def test_multiple_default_topologies_fail(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.clab.yml").write_text("topology: {}\n", encoding="utf-8")
            (root / "b.clab.yml").write_text("topology: {}\n", encoding="utf-8")
            with self.assertRaises(WanError):
                topology_path_from_args((), root)


class WanBridgeParsingTest(unittest.TestCase):
    def test_eclab_dhcp_wan_bridge_defaults(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "lab.clab.yml"
            path.write_text(
                """
topology:
  nodes:
    wan:
      kind: bridge
      labels:
        ECLAB_DHCP_WAN: "true"
""",
                encoding="utf-8",
            )

            bridges = dhcp_wan_bridges(load_topology(path), WanContract("ECLAB"))

        self.assertEqual(len(bridges), 1)
        self.assertEqual(bridges[0].name, "wan")
        self.assertEqual(str(bridges[0].subnet), "198.19.0.0/24")

    def test_arbitrary_contract_prefix_selects_all_settings(self) -> None:
        # WanContract itself stays prefix-agnostic; only wan_contract() is fixed.
        data = {
            "topology": {
                "nodes": {
                    "wan": {
                        "kind": "bridge",
                        "labels": {
                            "VENDOR_CLAB_DHCP_WAN": "true",
                            "VENDOR_CLAB_DHCP_SUBNET": "192.0.2.0/24",
                            "VENDOR_CLAB_DHCP_GATEWAY": "192.0.2.1",
                            "VENDOR_CLAB_DHCP_POOL_START": "192.0.2.20",
                            "VENDOR_CLAB_DHCP_POOL_END": "192.0.2.30",
                            "VENDOR_CLAB_DHCP_DNS": "192.0.2.53",
                            "VENDOR_CLAB_DHCP_LEASE_TIME": "600",
                        },
                    }
                }
            }
        }

        bridges = dhcp_wan_bridges(data, WanContract("VENDOR_CLAB"))

        self.assertEqual(str(bridges[0].subnet), "192.0.2.0/24")
        self.assertEqual(str(bridges[0].gateway), "192.0.2.1")
        self.assertEqual(bridges[0].lease_time, 600)

    def test_mismatched_prefix_label_is_rejected(self) -> None:
        data = {
            "topology": {
                "nodes": {
                    "wan": {
                        "kind": "bridge",
                        "labels": {"FCLAB_DHCP_WAN": "true"},
                    }
                }
            }
        }

        with self.assertRaisesRegex(WanError, "use ECLAB_DHCP_WAN"):
            dhcp_wan_bridges(data, WanContract("ECLAB"))


class PrefixTest(unittest.TestCase):
    def test_wan_contract_prefix_is_always_eclab(self) -> None:
        self.assertEqual(wan_contract().prefix, "ECLAB")
        self.assertEqual(LABEL_PREFIX, "ECLAB")

    def test_uplink_environment_uses_fixed_prefix(self) -> None:
        self.assertEqual(
            detect_uplink_interface(
                wan_contract(),
                {"ECLAB_UPLINK_IF": "ens3"},
            ),
            "ens3",
        )


if __name__ == "__main__":
    unittest.main()
