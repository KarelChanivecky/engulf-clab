from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from engulf_clab_mcp.config import load_config
from engulf_clab_mcp.errors import RequestError
from engulf_clab_mcp.security import (
    reject_license_source_overrides,
    reject_vrnetlab_source_overrides,
    sanitize_caller_overrides,
)


class ConfigAndSecurityTests(unittest.TestCase):
    def test_loads_profile_and_rejects_secret_or_runtime_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "tool"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
            labs = root / "labs"
            labs.mkdir()
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
                        'environment = { NORMAL = "value" }',
                        'secrets = { POOL = "secret" }',
                    ]
                ),
                encoding="utf-8",
            )
            config_path.chmod(0o600)
            config = load_config(config_path)
            self.assertEqual(config.profile(None).environment["NORMAL"], "value")
            self.assertEqual(
                sanitize_caller_overrides({"NORMAL": "override"}, secret_names=frozenset({"POOL"})),
                {"NORMAL": "override"},
            )
            with self.assertRaisesRegex(RequestError, "profile-owned"):
                sanitize_caller_overrides({"POOL": "other"}, secret_names=frozenset({"POOL"}))
            with self.assertRaisesRegex(RequestError, "controlled by the service"):
                sanitize_caller_overrides({"PATH": "/tmp"}, secret_names=frozenset())

    def test_license_pool_variable_cannot_be_caller_owned(self) -> None:
        document = {"topology": {"nodes": {"router": {"license": "$ROUTER_POOL"}}}}
        with self.assertRaisesRegex(RequestError, "selected profile"):
            reject_license_source_overrides(document, {"ROUTER_POOL": "/tmp/licenses"})

    def test_environment_values_reject_control_characters(self) -> None:
        with self.assertRaisesRegex(RequestError, "control character"):
            sanitize_caller_overrides({"SAFE": "one\ntwo"}, secret_names=frozenset())

    def test_vrnetlab_source_variable_cannot_be_caller_owned(self) -> None:
        document = {
            "name": "demo",
            "topology": {
                "nodes": {
                    "router": {
                        "env": {"ECLAB_VRNETLAB_IMG_PATH": "$IMAGE_SOURCE"},
                    }
                }
            },
        }
        with self.assertRaisesRegex(RequestError, "vrnetlab image source"):
            reject_vrnetlab_source_overrides(document, {"IMAGE_SOURCE": "/tmp/image"}, lab_name="demo")


if __name__ == "__main__":
    unittest.main()
