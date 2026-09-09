from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from engulf_clab_demo_lab import BUNDLE_FORMAT, DISTRIBUTION_VERSION
from engulf_clab_demo_lab.install import MARKER, main


def invoke(*arguments: str) -> int:
    with patch("sys.argv", ["eclab-demo-lab-install", *arguments]):
        return main()


def test_install_needs_no_external_input() -> None:
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "lab"
        assert invoke(str(target)) == 0

        marker = json.loads((target / MARKER).read_text(encoding="utf-8"))
        assert marker["format"] == BUNDLE_FORMAT
        assert marker["version"] == DISTRIBUTION_VERSION
        assert (target / "artifacts").is_dir()
        assert not (target / "local").exists()
        assert not (target / "licenses").exists()
        assert not (target / "inputs").exists()
        assert os.access(target / "run-eclab.sh", os.X_OK)
        assert invoke(str(target)) == 0
        assert invoke(str(target), "--check") == 0

        (target / ".engulf-clab-lab-deadbeef.clab.yml").write_text("name: derived\n")
        (target / "clab-eclab-all-features").mkdir()
        (target / "clab-eclab-all-features/topology-data.json").write_text("{}\n")
        (target / ".eclab").mkdir()
        (target / ".eclab/runtime.json").write_text("{}\n")
        assert invoke(str(target), "--check") == 0


def test_rejects_symlink_target() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        real = root / "real"
        real.mkdir()
        link = root / "lab"
        link.symlink_to(real, target_is_directory=True)
        with pytest.raises(SystemExit, match="destination must not be a symlink"):
            invoke(str(link))


def test_changed_install_requires_replace_and_is_backed_up() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        target = root / "lab"
        invoke(str(target))
        (target / "RUNBOOK.md").write_text("changed\n", encoding="utf-8")

        with pytest.raises(SystemExit, match="packaged files.*have changed"):
            invoke(str(target))

        assert invoke(str(target), "--replace") == 0
        backups = list((root / ".lab-backups").iterdir())
        assert len(backups) == 1
        assert (backups[0] / "RUNBOOK.md").read_text(encoding="utf-8") == "changed\n"
        assert invoke(str(target), "--check") == 0


def test_check_rejects_replace() -> None:
    with (
        tempfile.TemporaryDirectory() as directory,
        pytest.raises(SystemExit, match="--check cannot be combined with --replace"),
    ):
        invoke(str(Path(directory) / "lab"), "--check", "--replace")


def test_replace_accepts_owned_previous_bundle_format() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        target = root / "lab"
        target.mkdir()
        (target / MARKER).write_text(
            json.dumps({
                "distribution": "engulf-clab-demo-lab",
                "format": 1,
                "version": "0.3.0",
                "files": {},
            }),
            encoding="utf-8",
        )
        assert invoke(str(target), "--replace") == 0
        assert invoke(str(target), "--check") == 0
