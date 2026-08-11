from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from engulf import WorkspaceContext
from engulf_api import Invocation

from engulf_clab.workspace import topology_source_from_args, workspace_root


def context(cwd: Path, args: tuple[str, ...]) -> WorkspaceContext:
    return WorkspaceContext(
        application_id="engulf-clab",
        invocation=Invocation(args, cwd, {}),
    )


class TopologySourceTest(unittest.TestCase):
    def test_separate_and_assigned_options(self) -> None:
        self.assertEqual(
            topology_source_from_args(("deploy", "-t", "lab.yml")), "lab.yml"
        )
        self.assertEqual(
            topology_source_from_args(("destroy", "--topo=labs/one.clab.yml")),
            "labs/one.clab.yml",
        )

    def test_missing_or_absent_value_returns_none(self) -> None:
        self.assertIsNone(topology_source_from_args(("deploy",)))
        self.assertIsNone(topology_source_from_args(("deploy", "--topo")))
        self.assertIsNone(topology_source_from_args(("deploy", "--topo=")))


class WorkspaceRootTest(unittest.TestCase):
    def test_topology_file_selects_its_directory(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            lab = root / "labs"
            lab.mkdir()
            topology = lab / "one.clab.yml"
            topology.write_text("topology: {}\n", encoding="utf-8")

            resolved = workspace_root(context(root, ("deploy", "-t", str(topology))))

        self.assertEqual(resolved, lab)

    def test_topology_directory_is_the_workspace(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            lab = root / "lab"
            lab.mkdir()

            resolved = workspace_root(context(root, ("destroy", "--topo", "lab")))

        self.assertEqual(resolved, lab)

    def test_non_filesystem_sources_use_current_directory(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for source in ("stdin", "-", "https://example.test/lab.yml"):
                with self.subTest(source=source):
                    self.assertEqual(
                        workspace_root(context(root, ("deploy", "-t", source))),
                        root,
                    )

    def test_default_topology_uses_current_directory(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(workspace_root(context(root, ("deploy",))), root)


if __name__ == "__main__":
    unittest.main()
