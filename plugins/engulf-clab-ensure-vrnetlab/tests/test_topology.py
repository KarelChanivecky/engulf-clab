from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from engulf_clab_ensure_vrnetlab.topology import (
    topology_needs_vrnetlab,
    topology_path_from_args,
)


class TopologyTest(unittest.TestCase):
    def test_explicit_topology_options(self) -> None:
        self.assertEqual(topology_path_from_args(("-t", "lab.yml")), Path("lab.yml"))
        self.assertEqual(
            topology_path_from_args(("--topo=labs/one.yml",)),
            Path("labs/one.yml"),
        )

    def test_default_topology(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            topology = root / "lab.clab.yml"
            topology.write_text("topology: {}\n", encoding="utf-8")
            self.assertEqual(topology_path_from_args((), root), topology)

    def test_only_nonempty_builder_type_activates(self) -> None:
        self.assertTrue(
            topology_needs_vrnetlab(
                {
                    "topology": {
                        "nodes": {"router": {"env": {"ECLAB_VRNETLAB_TYPE": "vendor/router"}}}
                    }
                }
            )
        )

    def test_vendor_prefix_selects_only_its_own_nodes(self) -> None:
        topology = {
            "topology": {
                "nodes": {
                    "vendor": {"env": {"ACME_CLAB_VRNETLAB_TYPE": "vendor/router"}},
                    "official": {"env": {"ECLAB_VRNETLAB_TYPE": "vendor/router"}},
                }
            }
        }

        self.assertTrue(topology_needs_vrnetlab(topology, application_name="acme-clab"))
        self.assertTrue(topology_needs_vrnetlab(topology, application_name="engulf-clab"))
        self.assertFalse(topology_needs_vrnetlab(topology, application_name="other-clab"))
        self.assertFalse(
            topology_needs_vrnetlab(
                {
                    "topology": {
                        "nodes": {
                            "router": {"env": {"ECLAB_VRNETLAB_TYPE": "  "}},
                            "client": {"image": "alpine"},
                        }
                    }
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
