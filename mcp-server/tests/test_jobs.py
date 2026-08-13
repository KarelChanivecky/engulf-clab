from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

from engulf_clab_mcp.errors import BusyError
from engulf_clab_mcp.jobs import JobManager


class JobManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_runs_fixed_job_and_returns_bounded_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = self._manager(root)
            await manager.start()
            job = await manager.submit(
                operation="deploy",
                lab_id="labs:demo/lab.clab.yml",
                profile="default",
                argv=(sys.executable, "-c", "print('hello from job')"),
                environment={"PATH": "/usr/bin:/bin"},
                cwd=root,
                peer_uid=1000,
                peer_pid=2000,
            )
            await self._wait(job)
            self.assertEqual(job.state, "succeeded")
            self.assertIn("hello from job", manager.logs(job.identifier)["lines"])

    async def test_serializes_lifecycle_operations_per_lab(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = self._manager(root)
            await manager.start()
            first = await manager.submit(
                operation="deploy",
                lab_id="labs:demo/lab.clab.yml",
                profile="default",
                argv=(sys.executable, "-c", "import time; time.sleep(2)"),
                environment={"PATH": "/usr/bin:/bin"},
                cwd=root,
                peer_uid=None,
                peer_pid=None,
            )
            with self.assertRaises(BusyError) as raised:
                await manager.submit(
                    operation="destroy",
                    lab_id="labs:demo/lab.clab.yml",
                    profile="default",
                    argv=(sys.executable, "-c", "pass"),
                    environment={"PATH": "/usr/bin:/bin"},
                    cwd=root,
                    peer_uid=None,
                    peer_pid=None,
                )
            self.assertEqual(raised.exception.job_id, first.identifier)
            await manager.cancel(first.identifier)
            await self._wait(first)
            self.assertEqual(first.state, "cancelled")

    @staticmethod
    def _manager(root: Path) -> JobManager:
        return JobManager(
            state_dir=root / "state",
            log_dir=root / "logs",
            max_log_bytes=65536,
            max_read_bytes=8192,
            retention_days=1,
            cancel_grace_seconds=0.1,
            audit=lambda _event, _job: None,
        )

    @staticmethod
    async def _wait(job) -> None:
        for _ in range(300):
            if job.state in {"succeeded", "failed", "cancelled"}:
                return
            await asyncio.sleep(0.01)
        raise AssertionError("job did not finish")


if __name__ == "__main__":
    unittest.main()
