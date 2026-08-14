from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from engulf_api import StateStore, WorkspaceState
from engulf_clab import ContainerlabApp

from engulf_clab_wan.networks import METADATA_FILENAME


class EngulfStateIntegrationTest(unittest.TestCase):
    def test_destroy_all_discovers_and_destroys_every_workspace(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            state_home = root / "state-home"
            topology_paths: list[Path] = []
            for name in ("first", "second"):
                workspace = root / name
                workspace.mkdir()
                topology = workspace / "lab.clab.yml"
                topology.write_text(
                    "topology:\n  nodes:\n    wan:\n      kind: bridge\n"
                    "      labels: {ECLAB_DHCP_WAN: 'true'}\n",
                    encoding="utf-8",
                )
                topology_paths.append(topology)

            plugin_dir = root / "plugins"
            plugin_dir.mkdir()
            (plugin_dir / "lab_parser.py").write_text(
                "from engulf_clab_lab_parser import plugin\n",
                encoding="utf-8",
            )
            (plugin_dir / "lab_writer.py").write_text(
                "from engulf_clab_lab_writer import plugin\n",
                encoding="utf-8",
            )
            (plugin_dir / "wan.py").write_text(
                "from engulf_clab_wan.plugin import plugin\n",
                encoding="utf-8",
            )
            wrapper = ContainerlabApp(
                "/bin/true",
                plugin_dir=plugin_dir,
                discover_installed=False,
                state_home_resolver=lambda _context: state_home,
            )

            def seed_state(
                _topology: object,
                workspace_state: WorkspaceState,
                _user_state: StateStore,
                _contract: object,
            ) -> None:
                workspace_state.write_text(METADATA_FILENAME, "[]\n")

            cleaned_roots: list[Path] = []

            def clean_state(
                workspace_state: WorkspaceState, _user_state: StateStore
            ) -> None:
                cleaned_roots.append(workspace_state.root)
                workspace_state.destroy()

            with (
                patch(
                    "engulf_clab_wan.plugin.setup_dhcp_wan_bridges",
                    side_effect=seed_state,
                ),
                patch(
                    "engulf_clab_wan.plugin.cleanup_dhcp_wan_bridges",
                    side_effect=clean_state,
                ),
            ):
                for topology in topology_paths:
                    self.assertEqual(wrapper.run(("deploy", "-t", str(topology))), 0)
                self.assertEqual(wrapper.run(("destroy", "--all")), 0)

            self.assertEqual(
                set(cleaned_roots),
                {topology.parent.resolve() for topology in topology_paths},
            )
            self.assertEqual(list(state_home.rglob(METADATA_FILENAME)), [])


if __name__ == "__main__":
    unittest.main()
