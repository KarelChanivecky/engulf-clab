from __future__ import annotations

import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from engulf_api import WorkspaceState

from engulf_clab_wan.errors import WanError
from engulf_clab_wan.networks import (
    METADATA_FILENAME,
    cleanup_dhcp_wan_bridges,
    load_metadata,
    save_metadata,
    stop_pid_file,
)


class FilesystemWorkspaceState(WorkspaceState):
    def __init__(self, root: Path, directory: Path) -> None:
        self._root = root
        self._directory = directory
        self.destroyed = False

    @property
    def directory(self) -> Path:
        self._directory.mkdir(parents=True, exist_ok=True)
        return self._directory

    def path(self, filename: str) -> Path:
        return self.directory / filename

    def exists(self, filename: str) -> bool:
        return (self._directory / filename).exists()

    def read_bytes(self, filename: str) -> bytes:
        return (self._directory / filename).read_bytes()

    def read_text(
        self,
        filename: str,
        *,
        encoding: str = "utf-8",
        errors: str = "strict",
    ) -> str:
        return (self._directory / filename).read_text(encoding=encoding, errors=errors)

    def write_bytes(self, filename: str, data: bytes) -> None:
        self.path(filename).write_bytes(data)

    def write_text(
        self,
        filename: str,
        data: str,
        *,
        encoding: str = "utf-8",
        errors: str = "strict",
    ) -> None:
        self.path(filename).write_text(data, encoding=encoding, errors=errors)

    def delete(self, filename: str, *, missing_ok: bool = False) -> None:
        (self._directory / filename).unlink(missing_ok=missing_ok)

    @contextmanager
    def transaction(
        self, *, timeout: float | None = None
    ) -> Iterator[FilesystemWorkspaceState]:
        del timeout
        yield self

    @property
    def root(self) -> Path:
        return self._root

    def destroy(self) -> None:
        self.destroyed = True


def bridge_metadata() -> dict[str, object]:
    return {
        "name": "wan",
        "subnet": "198.19.0.0/24",
        "gateway": "198.19.0.1",
        "pool_start": "198.19.0.100",
        "pool_end": "198.19.0.200",
        "dns": "1.1.1.1",
        "lease_time": 43200,
        "created": True,
        "uplink": "eth0",
    }


class WorkspaceStateTest(unittest.TestCase):
    def test_metadata_round_trip_uses_managed_state(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            state = FilesystemWorkspaceState(root, root / "state")
            entries = [bridge_metadata()]

            save_metadata(state, entries)

            self.assertEqual(load_metadata(state), entries)
            self.assertTrue(state.exists(METADATA_FILENAME))

    def test_empty_cleanup_destroys_workspace_namespace(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            state = FilesystemWorkspaceState(root, root / "state")

            cleanup_dhcp_wan_bridges(state, state)

            self.assertTrue(state.destroyed)

    @patch("engulf_clab_wan.networks.restore_ip_forwarding_if_unused")
    @patch("engulf_clab_wan.networks.complete_release", return_value=True)
    @patch("engulf_clab_wan.networks.release_bridge")
    @patch("engulf_clab_wan.networks.workspace_bridge_names", return_value=["wan"])
    @patch("engulf_clab_wan.networks.cleanup_entry")
    @patch("engulf_clab_wan.networks.require_commands")
    @patch("engulf_clab_wan.networks.require_root")
    def test_successful_cleanup_destroys_workspace_namespace(
        self,
        _require_root: Mock,
        require_commands: Mock,
        cleanup_entry: Mock,
        _names: Mock,
        release: Mock,
        _complete: Mock,
        _restore: Mock,
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            state = FilesystemWorkspaceState(root, root / "state")
            entry = bridge_metadata()
            release.return_value = entry

            cleanup_dhcp_wan_bridges(state, state)

            require_commands.assert_called_once()
            cleanup_entry.assert_called_once_with(state, entry)
            self.assertTrue(state.destroyed)

    @patch("engulf_clab_wan.networks.release_bridge")
    @patch(
        "engulf_clab_wan.networks.workspace_bridge_names", return_value=["wan", "wan2"]
    )
    @patch(
        "engulf_clab_wan.networks.cleanup_entry",
        side_effect=(WanError("failed"), None),
    )
    @patch("engulf_clab_wan.networks.require_commands")
    @patch("engulf_clab_wan.networks.require_root")
    def test_failed_cleanup_keeps_workspace_state(
        self,
        _require_root: Mock,
        _require_commands: Mock,
        _cleanup_entry: Mock,
        _names: Mock,
        release: Mock,
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            state = FilesystemWorkspaceState(root, root / "state")
            first = bridge_metadata()
            second = {**bridge_metadata(), "name": "wan2"}
            release.side_effect = (first, second)

            with self.assertRaises(WanError):
                cleanup_dhcp_wan_bridges(state, state)

            self.assertEqual(_cleanup_entry.call_count, 2)
            self.assertFalse(state.destroyed)

    @patch("engulf_clab_wan.networks.time.sleep")
    @patch("engulf_clab_wan.networks.os.kill")
    @patch("engulf_clab_wan.networks.managed_dhcp_process", return_value=True)
    @patch("engulf_clab_wan.networks.process_alive", return_value=True)
    def test_unstoppable_dhcp_process_keeps_pid_state(
        self,
        _process_alive: Mock,
        _managed_process: Mock,
        _kill: Mock,
        _sleep: Mock,
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            state = FilesystemWorkspaceState(root, root / "state")
            state.write_text("wan.dhcp.pid", "123\n")

            with self.assertRaisesRegex(WanError, "did not stop"):
                stop_pid_file(state, "wan.dhcp.pid")

            self.assertTrue(state.exists("wan.dhcp.pid"))


if __name__ == "__main__":
    unittest.main()
