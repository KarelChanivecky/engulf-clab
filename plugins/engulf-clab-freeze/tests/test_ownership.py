from __future__ import annotations

import stat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from engulf_clab_freeze.ownership import restore_sudo_ownership


def test_restore_sudo_ownership_returns_root_owned_archive_to_invoker(tmp_path, monkeypatch):
    archive = tmp_path / "lab.tar.gz"
    archive.write_bytes(b"archive")
    monkeypatch.setenv("SUDO_UID", "1000")
    monkeypatch.setenv("SUDO_GID", "1001")

    with (
        patch("engulf_clab_freeze.ownership.os.geteuid", return_value=0),
        patch.object(
            Path,
            "stat",
            return_value=SimpleNamespace(st_mode=stat.S_IFREG, st_uid=0),
        ),
        patch("engulf_clab_freeze.ownership.os.chown") as chown,
    ):
        restore_sudo_ownership(archive)

    chown.assert_called_once_with(archive, 1000, 1001, follow_symlinks=False)


def test_restore_sudo_ownership_preserves_selected_root_owned_file(tmp_path, monkeypatch):
    binary = tmp_path / "containerlab"
    binary.write_bytes(b"binary")
    monkeypatch.setenv("SUDO_UID", "1000")
    monkeypatch.setenv("SUDO_GID", "1001")

    with (
        patch("engulf_clab_freeze.ownership.os.geteuid", return_value=0),
        patch.object(
            Path,
            "stat",
            return_value=SimpleNamespace(st_mode=stat.S_IFREG, st_uid=0),
        ),
        patch("engulf_clab_freeze.ownership.os.chown") as chown,
    ):
        restore_sudo_ownership(binary, preserve=(binary,))

    chown.assert_not_called()
