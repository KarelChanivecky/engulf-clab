from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from engulf_clab_wan.errors import WanError
from engulf_clab_wan.networks import dhcp_wan_bridges
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
    def test_fclab_dhcp_wan_bridge_defaults(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "lab.clab.yml"
            path.write_text(
                """
topology:
  nodes:
    wan:
      kind: bridge
      labels:
        FCLAB_DHCP_WAN: "true"
""",
                encoding="utf-8",
            )

            bridges = dhcp_wan_bridges(load_topology(path))

        self.assertEqual(len(bridges), 1)
        self.assertEqual(bridges[0].name, "wan")
        self.assertEqual(str(bridges[0].subnet), "198.19.0.0/24")


if __name__ == "__main__":
    unittest.main()
