from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from engulf_clab_mcp.config import load_config
from engulf_clab_mcp.daemon import LocalDaemon, main


class DaemonTests(unittest.IsolatedAsyncioTestCase):
    async def test_daemon_serves_bounded_local_rpc(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "tool"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
            labs = root / "labs"
            labs.mkdir()
            (labs / "lab.clab.yml").write_text("topology: {nodes: {router: {}}}\n", encoding="utf-8")
            config_path = root / "config.toml"
            config_path.write_text(
                "\n".join(
                    [
                        "[service]",
                        f'socket_path = "{root / "run" / "service.sock"}"',
                        'socket_group = "eclab-mcp"',
                        f'eclab_binary = "{executable}"',
                        f'containerlab_binary = "{executable}"',
                        f'docker_binary = "{executable}"',
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
            daemon = LocalDaemon(load_config(config_path))
            try:
                await daemon.start()
            except PermissionError:
                self.skipTest("the execution sandbox does not permit Unix socket creation")
            try:
                reader, writer = await asyncio.open_unix_connection(str(root / "run" / "service.sock"))
                writer.write(
                    json.dumps(
                        {"version": 1, "id": "request", "method": "labs.list", "params": {}}
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()
                response = json.loads(await reader.readline())
                writer.close()
                await writer.wait_closed()
            finally:
                await daemon.close()
            self.assertTrue(response["ok"])
            self.assertEqual(response["result"]["labs"][0]["id"], "labs:lab.clab.yml")

    @patch("engulf_clab_mcp.daemon.asyncio.run")
    @patch("engulf_clab_mcp.daemon.load_config")
    @patch("engulf_clab_mcp.daemon.os.geteuid", return_value=0)
    def test_check_config_exits_without_starting_the_daemon(
        self, _geteuid: Any, load: Any, run: Any
    ) -> None:
        self.assertEqual(main(["--config", "/etc/eclab-mcp/config.toml", "--check-config"]), 0)
        load.assert_called_once_with(Path("/etc/eclab-mcp/config.toml"))
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
