from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from engulf_clab_mcp.config import load_config
from engulf_clab_mcp.labs import LabCatalog


class LabCatalogTests(unittest.TestCase):
    def test_discovers_rooted_labs_and_excludes_escape_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "tool"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
            labs = root / "labs"
            demo = labs / "demo"
            demo.mkdir(parents=True)
            (demo / "lab.clab.yml").write_text(
                "name: demo\ntopology:\n  nodes:\n    router: {}\n", encoding="utf-8"
            )
            outside = root / "outside.clab.yml"
            outside.write_text("topology: {nodes: {outside: {}}}\n", encoding="utf-8")
            (labs / "escape.clab.yml").symlink_to(outside)
            config = self._config(root, executable, labs)
            catalog = LabCatalog(config)
            labs_found = catalog.list_labs()
            self.assertEqual([lab.identifier for lab in labs_found], ["labs:demo/lab.clab.yml"])
            self.assertEqual(labs_found[0].display_name, "demo")
            self.assertEqual(catalog.resolve("labs:demo/lab.clab.yml").path, (demo / "lab.clab.yml"))

    @staticmethod
    def _config(root: Path, executable: Path, labs: Path):
        config_path = root / "config.toml"
        config_path.write_text(
            "\n".join(
                [
                    "[service]",
                    f'eclab_binary = "{executable}"',
                    f'containerlab_binary = "{executable}"',
                    f'docker_binary = "{executable}"',
                    f'socket_path = "{root / "service.sock"}"',
                    f'state_dir = "{root / "state"}"',
                    f'log_dir = "{root / "logs"}"',
                    "",
                    "[[lab_roots]]",
                    'id = "labs"',
                    f'path = "{labs}"',
                    "",
                    "[profiles.default]",
                    "environment = {}",
                    "secrets = {}",
                ]
            ),
            encoding="utf-8",
        )
        config_path.chmod(0o600)
        return load_config(config_path)


if __name__ == "__main__":
    unittest.main()
