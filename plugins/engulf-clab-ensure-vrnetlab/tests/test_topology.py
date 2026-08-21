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
        self.assertEqual(topology_path_from_args(("-t", "lab.yml")), Path("lab.yml").resolve())
        self.assertEqual(
            topology_path_from_args(("--topo=labs/one.yml",)),
            Path("labs/one.yml").resolve(),
        )

    def test_default_topology(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            topology = root / "lab.clab.yml"
            topology.write_text("topology: {}\n", encoding="utf-8")
            self.assertEqual(topology_path_from_args((), root), topology.resolve())

    def test_default_topology_ignores_writer_residue(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            topology = root / "lab.clab.yml"
            topology.write_text("topology: {}\n", encoding="utf-8")
            (root / ".engulf-clab-lab-stale.clab.yml").write_text(
                "topology: {}\n", encoding="utf-8"
            )

            self.assertEqual(topology_path_from_args((), root), topology.resolve())

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

    def test_fixed_prefix_ignores_other_prefixes(self) -> None:
        topology = {
            "topology": {
                "nodes": {
                    "vendor": {"env": {"ACME_CLAB_VRNETLAB_TYPE": "vendor/router"}},
                    "official": {"env": {"ECLAB_VRNETLAB_TYPE": "vendor/router"}},
                }
            }
        }

        self.assertTrue(topology_needs_vrnetlab(topology))
        self.assertFalse(
            topology_needs_vrnetlab(
                {
                    "topology": {
                        "nodes": {
                            "vendor": {"env": {"ACME_CLAB_VRNETLAB_TYPE": "vendor/router"}},
                        }
                    }
                }
            )
        )
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
