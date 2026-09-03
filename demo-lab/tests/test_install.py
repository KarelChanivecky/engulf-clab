from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from engulf_clab_demo_lab import BUNDLE_FORMAT, DISTRIBUTION_VERSION
from engulf_clab_demo_lab.install import MARKER, main


def invoke(*arguments: str) -> int:
    with patch("sys.argv", ["eclab-demo-lab-install", *arguments]):
        return main()


def test_install_records_external_image_and_creates_empty_pool() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        image = root / "fortios-v8.0.0.qcow2"
        image.write_bytes(b"external-test-image")
        target = root / "lab"

        assert invoke(str(target), "--fortigate-image", str(image)) == 0

        marker = json.loads((target / MARKER).read_text(encoding="utf-8"))
        assert marker["format"] == BUNDLE_FORMAT
        assert marker["version"] == DISTRIBUTION_VERSION
        assert str(image) in (target / "local/runtime.env").read_text(encoding="utf-8")
        assert list((target / "inputs/licenses").iterdir()) == []
        assert not any(path.suffix == ".qcow2" for path in target.rglob("*"))
        assert stat.S_IMODE((target / "local/runtime.env").stat().st_mode) == 0o600
        assert os.access(target / "run-eclab.sh", os.X_OK)
        assert invoke(str(target)) == 0
        assert invoke(str(target), "--check") == 0


def test_noninteractive_install_requires_image() -> None:
    with (
        tempfile.TemporaryDirectory() as directory,
        patch("sys.stdin.isatty", return_value=False),
        pytest.raises(SystemExit, match="--fortigate-image is required"),
    ):
        invoke(str(Path(directory) / "lab"))


def test_rejects_unsupported_image_and_symlink_target() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        bad = root / "fortios.img"
        bad.write_bytes(b"not-supported")
        with pytest.raises(SystemExit, match="must be .qcow2"):
            invoke(str(root / "lab"), "--fortigate-image", str(bad))

        image = root / "fortios.qcow2"
        image.write_bytes(b"image")
        real = root / "real"
        real.mkdir()
        link = root / "lab"
        link.symlink_to(real, target_is_directory=True)
        with pytest.raises(SystemExit, match="destination must not be a symlink"):
            invoke(str(link), "--fortigate-image", str(image))


def test_changed_install_requires_replace_and_is_backed_up() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        image = root / "fortios.qcow2"
        image.write_bytes(b"image")
        target = root / "lab"
        invoke(str(target), "--fortigate-image", str(image))
        (target / "RUNBOOK.md").write_text("changed\n", encoding="utf-8")

        with pytest.raises(SystemExit, match="packaged files.*have changed"):
            invoke(str(target), "--fortigate-image", str(image))

        assert invoke(str(target), "--fortigate-image", str(image), "--replace") == 0
        backups = list((root / ".lab-backups").iterdir())
        assert len(backups) == 1
        assert (backups[0] / "RUNBOOK.md").read_text(encoding="utf-8") == "changed\n"
        assert invoke(str(target), "--check") == 0
