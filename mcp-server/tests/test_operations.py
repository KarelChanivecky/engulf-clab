from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

from engulf_clab_mcp.config import load_config
from engulf_clab_mcp.errors import RequestError
from engulf_clab_mcp.jobs import JobManager
from engulf_clab_mcp.labs import LabCatalog
from engulf_clab_mcp.operations import LabOperations, PeerIdentity


class OperationTests(unittest.IsolatedAsyncioTestCase):
    async def test_validate_status_logs_and_deploy_use_fixed_tools(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            labs = root / "labs"
            demo = labs / "demo"
            demo.mkdir(parents=True)
            (demo / "lab.clab.yml").write_text(
                "name: demo\ntopology:\n  nodes:\n    router: {}\n", encoding="utf-8"
            )
            eclab = self._script(
                root / "eclab",
                """
import json
import sys
arguments = sys.argv[1:]
if arguments == ["--engulf-plugin-list"]:
    print("engulf_clab.example")
elif arguments and arguments[0] == "inspect":
    print(json.dumps({"demo": [{"name": "/clab-demo-router", "state": "running", "status": "healthy"}]}))
elif arguments and arguments[0] in {"deploy", "destroy"}:
    print(arguments[0])
else:
    raise SystemExit(2)
""",
            )
            containerlab = self._script(
                root / "containerlab",
                """
import sys
if sys.argv[1:2] == ["graph"]:
    print("graph TD")
elif sys.argv[1:2] == ["version"]:
    print("containerlab v1")
else:
    raise SystemExit(2)
""",
            )
            docker = self._script(
                root / "docker",
                """
import sys
if sys.argv[1:2] == ["logs"]:
    print("router booted")
elif sys.argv[1:2] == ["version"]:
    print("docker v1")
else:
    raise SystemExit(2)
""",
            )
            config = self._config(root, labs, eclab, containerlab, docker)
            jobs = JobManager(
                state_dir=config.state_dir,
                log_dir=config.log_dir,
                max_log_bytes=config.max_job_log_bytes,
                max_read_bytes=config.max_read_output_bytes,
                retention_days=config.job_retention_days,
                cancel_grace_seconds=0.1,
                audit=lambda _event, _job: None,
            )
            await jobs.start()
            operations = LabOperations(config, LabCatalog(config), jobs)
            lab_id = "labs:demo/lab.clab.yml"

            _lab, _document, environment = operations._lab_environment(
                lab_id, "default", {"NORMAL": "caller"}
            )
            self.assertEqual(environment["NORMAL"], "caller")
            self.assertEqual(environment["SECRET"], "service-owned")
            self.assertEqual(environment["CONTAINERLAB_BIN"], str(containerlab))

            validation = await operations.validate(lab_id)
            self.assertTrue(validation["valid"])
            self.assertEqual(validation["nodes"], ["router"])

            status = await operations.status(lab_id, "default", {})
            self.assertTrue(status["available"])
            self.assertEqual(status["nodes"][0]["status"], "healthy")

            logs = await operations.node_logs(lab_id, "router", 20, "default", {})
            self.assertIn("router booted", logs["lines"])

            queued = await operations.deploy(lab_id, "default", {}, PeerIdentity(1000, 2000, 1000))
            job_id = queued["job"]["job_id"]
            self.assertIsInstance(job_id, str)
            await self._wait(jobs.status(job_id))
            self.assertEqual(jobs.status(job_id).state, "succeeded")

            with self.assertRaisesRegex(RequestError, "controlled by the service"):
                await operations.deploy(lab_id, "default", {"PATH": "/tmp"}, PeerIdentity(1, 1, 1))

    @staticmethod
    def _script(path: Path, body: str) -> Path:
        path.write_text(f"#!{sys.executable}\n{body.lstrip()}", encoding="utf-8")
        path.chmod(0o755)
        return path

    @staticmethod
    def _config(root: Path, labs: Path, eclab: Path, containerlab: Path, docker: Path):
        path = root / "config.toml"
        path.write_text(
            "\n".join(
                [
                    "[service]",
                    f'socket_path = "{root / "service.sock"}"',
                    'socket_group = "eclab-mcp"',
                    f'eclab_binary = "{eclab}"',
                    f'containerlab_binary = "{containerlab}"',
                    f'docker_binary = "{docker}"',
                    f'state_dir = "{root / "state"}"',
                    f'log_dir = "{root / "logs"}"',
                    "read_timeout_seconds = 5",
                    "",
                    "[[lab_roots]]",
                    'id = "labs"',
                    f'path = "{labs}"',
                    "",
                    "[profiles.default]",
                    'environment = { NORMAL = "profile" }',
                    'secrets = { SECRET = "service-owned" }',
                ]
            ),
            encoding="utf-8",
        )
        path.chmod(0o600)
        return load_config(path)

    @staticmethod
    async def _wait(job) -> None:
        for _ in range(300):
            if job.state in {"succeeded", "failed", "cancelled"}:
                return
            await asyncio.sleep(0.01)
        raise AssertionError("job did not finish")


if __name__ == "__main__":
    unittest.main()
