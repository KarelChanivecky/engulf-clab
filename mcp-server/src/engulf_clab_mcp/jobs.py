"""Durable, bounded asynchronous jobs for privileged eclab lifecycle calls."""

from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .errors import BusyError, NotFoundError, RequestError

_JOB_ID = re.compile(r"^[0-9a-f]{32}$")
_ACTIVE_STATES = frozenset({"queued", "running"})
_FINAL_STATES = frozenset({"succeeded", "failed", "cancelled"})


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class Job:
    """A single asynchronous fixed-argv operation."""

    identifier: str
    operation: str
    lab_id: str
    profile: str
    submitted_at: str
    peer_uid: int | None
    peer_pid: int | None
    state: str = "queued"
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    message: str | None = None
    log_truncated: bool = False
    cancel_requested: bool = False
    process: asyncio.subprocess.Process | None = field(default=None, repr=False)
    task: asyncio.Task[None] | None = field(default=None, repr=False)

    @property
    def process_is_running(self) -> bool:
        """Return whether this job currently owns a live subprocess."""
        return self.process is not None and self.process.returncode is None

    def public(self) -> dict[str, object]:
        """Return non-sensitive status suitable for the local MCP caller."""
        result: dict[str, object] = {
            "job_id": self.identifier,
            "operation": self.operation,
            "lab_id": self.lab_id,
            "profile": self.profile,
            "state": self.state,
            "submitted_at": self.submitted_at,
            "log_truncated": self.log_truncated,
        }
        if self.started_at is not None:
            result["started_at"] = self.started_at
        if self.finished_at is not None:
            result["finished_at"] = self.finished_at
        if self.exit_code is not None:
            result["exit_code"] = self.exit_code
        if self.message is not None:
            result["message"] = self.message
        return result

    def metadata(self) -> dict[str, object]:
        """Persist only audit-safe values; never persist argv or environment values."""
        return {
            "version": 1,
            "job_id": self.identifier,
            "operation": self.operation,
            "lab_id": self.lab_id,
            "profile": self.profile,
            "submitted_at": self.submitted_at,
            "peer_uid": self.peer_uid,
            "peer_pid": self.peer_pid,
            "state": self.state,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "exit_code": self.exit_code,
            "message": self.message,
            "log_truncated": self.log_truncated,
            "cancel_requested": self.cancel_requested,
        }

    @classmethod
    def from_metadata(cls, value: Mapping[str, object]) -> Job | None:
        """Best-effort loading for historical job reporting and restart recovery."""
        identifier = value.get("job_id")
        operation = value.get("operation")
        lab_id = value.get("lab_id")
        profile = value.get("profile")
        submitted_at = value.get("submitted_at")
        state = value.get("state")
        if not all(isinstance(item, str) for item in (identifier, operation, lab_id, profile, submitted_at, state)):
            return None
        if _JOB_ID.fullmatch(identifier) is None or state not in _ACTIVE_STATES | _FINAL_STATES:
            return None
        peer_uid = value.get("peer_uid")
        peer_pid = value.get("peer_pid")
        exit_code = value.get("exit_code")
        return cls(
            identifier=identifier,
            operation=operation,
            lab_id=lab_id,
            profile=profile,
            submitted_at=submitted_at,
            peer_uid=peer_uid if isinstance(peer_uid, int) else None,
            peer_pid=peer_pid if isinstance(peer_pid, int) else None,
            state=state,
            started_at=value.get("started_at") if isinstance(value.get("started_at"), str) else None,
            finished_at=value.get("finished_at") if isinstance(value.get("finished_at"), str) else None,
            exit_code=exit_code if isinstance(exit_code, int) else None,
            message=value.get("message") if isinstance(value.get("message"), str) else None,
            log_truncated=bool(value.get("log_truncated", False)),
            cancel_requested=bool(value.get("cancel_requested", False)),
        )


Audit = Callable[[str, Job], None]


class JobManager:
    """Owns process groups, serialized lab lifecycle work, and retained job records."""

    def __init__(
        self,
        *,
        state_dir: Path,
        log_dir: Path,
        max_log_bytes: int,
        max_read_bytes: int,
        retention_days: int,
        cancel_grace_seconds: float,
        audit: Audit,
    ) -> None:
        self._metadata_dir = state_dir / "jobs"
        self._log_dir = log_dir
        self._max_log_bytes = max_log_bytes
        self._max_read_bytes = max_read_bytes
        self._retention_days = retention_days
        self._cancel_grace_seconds = cancel_grace_seconds
        self._audit = audit
        self._jobs: dict[str, Job] = {}
        self._active_by_lab: dict[str, str] = {}

    async def start(self) -> None:
        """Load prior records, mark interrupted work, and remove expired history."""
        self._metadata_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._metadata_dir.chmod(0o700)
        self._log_dir.chmod(0o700)
        for path in sorted(self._metadata_dir.glob("*.json")):
            job = self._load(path)
            if job is None:
                continue
            if job.state in _ACTIVE_STATES:
                job.state = "failed"
                job.finished_at = _timestamp()
                job.message = "service restarted before this job completed"
                self._write(job)
            self._jobs[job.identifier] = job
        self._prune()

    async def submit(
        self,
        *,
        operation: str,
        lab_id: str,
        profile: str,
        argv: Sequence[str],
        environment: Mapping[str, str],
        cwd: Path,
        peer_uid: int | None,
        peer_pid: int | None,
    ) -> Job:
        """Queue one fixed invocation, returning a busy result for a lab conflict."""
        active = self._active_by_lab.get(lab_id)
        if active is not None:
            raise BusyError("a lifecycle job is already active for this lab", active)
        job = Job(
            identifier=uuid.uuid4().hex,
            operation=operation,
            lab_id=lab_id,
            profile=profile,
            submitted_at=_timestamp(),
            peer_uid=peer_uid,
            peer_pid=peer_pid,
        )
        self._jobs[job.identifier] = job
        self._active_by_lab[lab_id] = job.identifier
        self._write(job)
        self._audit("job submitted", job)
        job.task = asyncio.create_task(
            self._run(job, tuple(argv), dict(environment), cwd), name=f"eclab-mcp-{job.identifier}"
        )
        return job

    def status(self, identifier: object) -> Job:
        """Return one known job without treating job IDs as filesystem paths."""
        job_id = self._job_id(identifier)
        job = self._jobs.get(job_id)
        if job is None:
            raise NotFoundError("job ID is not known")
        return job

    def list(self, limit: object = 20) -> list[Job]:
        """Return retained jobs newest first with a bounded caller-selected limit."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise RequestError("limit must be an integer between 1 and 100")
        return sorted(self._jobs.values(), key=lambda job: job.submitted_at, reverse=True)[:limit]

    async def cancel(self, identifier: object) -> Job:
        """Request cancellation by terminating only the known job's process group."""
        job = self.status(identifier)
        if job.state not in _ACTIVE_STATES:
            return job
        job.cancel_requested = True
        job.message = "cancellation requested"
        self._write(job)
        if job.process is not None and job.process_is_running:
            self._terminate_group(job.process)
            asyncio.create_task(self._force_kill_after(job), name=f"eclab-mcp-cancel-{job.identifier}")
        self._audit("job cancellation requested", job)
        return job

    def logs(self, identifier: object, tail_lines: object = 200) -> dict[str, object]:
        """Read a bounded tail of one known root-owned job log."""
        job = self.status(identifier)
        if isinstance(tail_lines, bool) or not isinstance(tail_lines, int) or not 1 <= tail_lines <= 1000:
            raise RequestError("tail_lines must be an integer between 1 and 1000")
        path = self._log_path(job.identifier)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            raw = b""
        limited = len(raw) > self._max_read_bytes
        if limited:
            raw = raw[-self._max_read_bytes :]
        lines = raw.decode("utf-8", errors="replace").splitlines()
        return {
            "job_id": job.identifier,
            "state": job.state,
            "lines": "\n".join(lines[-tail_lines:]),
            "truncated": limited or job.log_truncated,
        }

    async def close(self) -> None:
        """Request termination of active process groups during daemon shutdown."""
        for job in tuple(self._jobs.values()):
            if job.state in _ACTIVE_STATES:
                await self.cancel(job.identifier)
        tasks = [job.task for job in self._jobs.values() if job.task is not None and not job.task.done()]
        if not tasks:
            return
        _done, pending = await asyncio.wait(
            tasks, timeout=min(self._cancel_grace_seconds + 2, 60)
        )
        for job in self._jobs.values():
            if job.task in pending and job.process is not None and job.process_is_running:
                try:
                    os.killpg(job.process.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
        if pending:
            await asyncio.wait(pending, timeout=5)

    async def _run(
        self, job: Job, argv: tuple[str, ...], environment: dict[str, str], cwd: Path
    ) -> None:
        if job.cancel_requested:
            job.state = "cancelled"
            job.finished_at = _timestamp()
            job.message = "cancelled before process start"
            self._finish(job)
            return
        job.state = "running"
        job.started_at = _timestamp()
        job.message = None
        self._write(job)
        self._audit("job started", job)
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(cwd),
                env=environment,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
            job.process = process
            if job.cancel_requested:
                self._terminate_group(process)
            assert process.stdout is not None
            copy_task = asyncio.create_task(self._copy_log(job, process.stdout))
            returncode = await process.wait()
            await copy_task
            job.exit_code = returncode
            if job.cancel_requested:
                job.state = "cancelled"
                job.message = "cancelled"
            elif returncode == 0:
                job.state = "succeeded"
                job.message = "completed"
            else:
                job.state = "failed"
                job.message = f"operation exited with status {returncode}"
        except (OSError, asyncio.SubprocessError):
            job.state = "failed"
            job.message = "service could not start the fixed operation"
        except Exception:  # noqa: BLE001 - prevent a failed log write from orphaning job state.
            job.state = "failed"
            job.message = "service could not complete the fixed operation"
        finally:
            job.process = None
            job.finished_at = _timestamp()
            self._finish(job)

    async def _copy_log(self, job: Job, stream: asyncio.StreamReader) -> None:
        remaining = self._max_log_bytes
        marker_written = False
        path = self._log_path(job.identifier)
        with path.open("wb") as handle:
            os.chmod(path, 0o600)
            while chunk := await stream.read(64 * 1024):
                available = remaining
                if available > 0:
                    accepted = chunk[:available]
                    handle.write(accepted)
                    remaining -= len(accepted)
                if len(chunk) > available:
                    job.log_truncated = True
                    if not marker_written:
                        handle.write(b"\n[eclab-mcp: job log truncated]\n")
                        marker_written = True
                # Keep draining even after the bound so the child cannot block on its pipe.

    async def _force_kill_after(self, job: Job) -> None:
        await asyncio.sleep(self._cancel_grace_seconds)
        process = job.process
        if job.state in _ACTIVE_STATES and process is not None and job.process_is_running:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    @staticmethod
    def _terminate_group(process: asyncio.subprocess.Process) -> None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                process.terminate()
            except ProcessLookupError:
                pass

    def _finish(self, job: Job) -> None:
        if job.state not in _FINAL_STATES:
            job.state = "failed"
            job.message = "service ended the job unexpectedly"
        self._active_by_lab.pop(job.lab_id, None)
        self._write(job)
        self._prune()
        self._audit("job finished", job)

    def _prune(self) -> None:
        cutoff = time.time() - self._retention_days * 24 * 60 * 60
        for identifier, job in tuple(self._jobs.items()):
            metadata = self._metadata_path(identifier)
            try:
                expired = metadata.stat().st_mtime < cutoff
            except FileNotFoundError:
                expired = False
            if not expired or job.state in _ACTIVE_STATES:
                continue
            metadata.unlink(missing_ok=True)
            self._log_path(identifier).unlink(missing_ok=True)
            self._jobs.pop(identifier, None)

    def _load(self, path: Path) -> Job | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return Job.from_metadata(value) if isinstance(value, Mapping) else None

    def _write(self, job: Job) -> None:
        target = self._metadata_path(job.identifier)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(job.metadata(), sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(target)

    def _metadata_path(self, identifier: str) -> Path:
        return self._metadata_dir / f"{identifier}.json"

    def _log_path(self, identifier: str) -> Path:
        return self._log_dir / f"{identifier}.log"

    @staticmethod
    def _job_id(value: object) -> str:
        if not isinstance(value, str) or _JOB_ID.fullmatch(value) is None:
            raise RequestError("job_id is invalid")
        return value
