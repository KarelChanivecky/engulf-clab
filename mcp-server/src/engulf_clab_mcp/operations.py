"""Narrow fixed-argv lab operations exposed through the local RPC daemon."""

from __future__ import annotations

import asyncio
import json
import os
import signal
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Profile, ServiceConfig
from .errors import McpServiceError, OperationError, RequestError
from .jobs import JobManager
from .labs import Lab, LabCatalog, topology_name, topology_nodes
from .security import (
    reject_license_source_overrides,
    reject_vrnetlab_source_overrides,
    sanitize_caller_overrides,
)


@dataclass(frozen=True, slots=True)
class PeerIdentity:
    """Kernel-provided local peer metadata retained for audit records."""

    uid: int | None
    pid: int | None
    gid: int | None


@dataclass(frozen=True, slots=True)
class Capture:
    """Bounded output from one fixed non-interactive subprocess invocation."""

    returncode: int
    stdout: bytes
    stderr: bytes
    stdout_truncated: bool
    stderr_truncated: bool
    timed_out: bool


class LabOperations:
    """Coordinates catalog validation, isolated environment, and known commands."""

    def __init__(self, config: ServiceConfig, catalog: LabCatalog, jobs: JobManager) -> None:
        self._config = config
        self._catalog = catalog
        self._jobs = jobs
        # JSON can escape a character into several bytes. Keep response text well
        # below a single private RPC frame rather than relying on transport fallback.
        self._response_text_limit = max(
            256, min(config.max_read_output_bytes, max(256, (config.max_rpc_frame_bytes - 2048) // 8))
        )

    async def list_labs(self) -> dict[str, object]:
        """Return only configured-root lab records and non-secret profile names."""
        return {
            "labs": [lab.public() for lab in self._catalog.list_labs()],
            "profiles": sorted(self._config.profiles),
        }

    async def validate(self, lab_id: object) -> dict[str, object]:
        """Parse one topology and run a read-only offline graph check."""
        lab = self._catalog.resolve(lab_id)
        try:
            document = self._catalog.load_document(lab)
            nodes = topology_nodes(document)
        except McpServiceError as error:
            return {"lab_id": lab.identifier, "valid": False, "message": error.message}
        capture = await self._capture(
            (str(self._config.containerlab_binary), "graph", "-t", str(lab.path), "--offline", "--mermaid"),
            self._base_environment(),
            cwd=lab.path.parent,
        )
        if capture.timed_out:
            return {"lab_id": lab.identifier, "valid": False, "message": "offline graph validation timed out"}
        if capture.returncode != 0:
            return {
                "lab_id": lab.identifier,
                "valid": False,
                "message": "offline Containerlab graph validation failed",
            }
        return {
            "lab_id": lab.identifier,
            "valid": True,
            "lab_name": topology_name(document, lab.path),
            "nodes": list(nodes),
            "graph": self._public_text(capture.stdout),
            "truncated": capture.stdout_truncated,
        }

    async def deploy(
        self,
        lab_id: object,
        profile_name: object,
        overrides: object,
        peer: PeerIdentity,
    ) -> dict[str, object]:
        """Queue only a full fixed `eclab deploy -t` invocation."""
        return await self._submit("deploy", lab_id, profile_name, overrides, peer)

    async def destroy(
        self,
        lab_id: object,
        profile_name: object,
        overrides: object,
        peer: PeerIdentity,
    ) -> dict[str, object]:
        """Queue only a full fixed `eclab destroy -t` invocation."""
        return await self._submit("destroy", lab_id, profile_name, overrides, peer)

    async def status(
        self,
        lab_id: object,
        profile_name: object,
        overrides: object,
    ) -> dict[str, object]:
        """Return normalized state/status from the configured eclab executable."""
        lab, document, environment = self._lab_environment(lab_id, profile_name, overrides)
        inspection = await self._inspect(lab, environment)
        if inspection is None:
            return {
                "lab_id": lab.identifier,
                "available": False,
                "nodes": [],
                "message": "eclab inspect did not return lab state",
            }
        return {
            "lab_id": lab.identifier,
            "available": True,
            "lab_name": topology_name(document, lab.path),
            "nodes": self._normalize_inspection(inspection),
        }

    async def node_logs(
        self,
        lab_id: object,
        node: object,
        tail_lines: object,
        profile_name: object,
        overrides: object,
    ) -> dict[str, object]:
        """Return bounded Docker logs for a node known to the selected topology."""
        if not isinstance(node, str) or not node:
            raise RequestError("node must be a nonempty topology node name")
        if isinstance(tail_lines, bool) or not isinstance(tail_lines, int) or not 1 <= tail_lines <= 1000:
            raise RequestError("tail_lines must be an integer between 1 and 1000")
        lab, document, environment = self._lab_environment(lab_id, profile_name, overrides)
        if node not in topology_nodes(document):
            raise RequestError("node is not declared by the selected topology")
        inspection = await self._inspect(lab, environment)
        if inspection is None:
            raise OperationError("the selected lab has no inspectable running nodes")
        container = self._container_for_node(
            inspection, node=node, expected_lab_name=topology_name(document, lab.path)
        )
        capture = await self._capture(
            (str(self._config.docker_binary), "logs", "--tail", str(tail_lines), container),
            environment,
            cwd=lab.path.parent,
        )
        if capture.timed_out:
            raise OperationError("Docker logs timed out")
        if capture.returncode != 0:
            raise OperationError("Docker could not read logs for the selected node")
        return {
            "lab_id": lab.identifier,
            "node": node,
            "container": container,
            "lines": self._public_text(capture.stdout),
            "truncated": capture.stdout_truncated,
        }

    async def diagnostics(
        self,
        lab_id: object | None,
        profile_name: object,
        overrides: object,
    ) -> dict[str, object]:
        """Collect bounded information only from fixed safe version/diagnostic commands."""
        profile = self._profile(profile_name)
        caller = sanitize_caller_overrides(overrides, secret_names=profile.secret_names)
        environment = self._invocation_environment(profile, caller)
        eclab = await self._capture(
            (str(self._config.eclab_binary), "--engulf-plugin-list"), environment, cwd=self._config.state_dir
        )
        containerlab = await self._capture(
            (str(self._config.containerlab_binary), "version"), environment, cwd=self._config.state_dir
        )
        docker = await self._capture(
            (str(self._config.docker_binary), "version", "--format", "{{.Server.Version}}"),
            environment,
            cwd=self._config.state_dir,
        )
        result: dict[str, object] = {
            "profile": profile.name,
            "eclab_plugins": self._public_text(eclab.stdout),
            "containerlab_version": self._first_line(containerlab.stdout),
            "docker_version": self._first_line(docker.stdout),
            "truncated": eclab.stdout_truncated
            or containerlab.stdout_truncated
            or docker.stdout_truncated,
        }
        if lab_id is not None:
            result["status"] = await self.status(lab_id, profile.name, caller)
        return result

    async def _submit(
        self,
        operation: str,
        lab_id: object,
        profile_name: object,
        overrides: object,
        peer: PeerIdentity,
    ) -> dict[str, object]:
        lab, _document, environment = self._lab_environment(lab_id, profile_name, overrides)
        job = await self._jobs.submit(
            operation=operation,
            lab_id=lab.identifier,
            profile=self._profile(profile_name).name,
            argv=(str(self._config.eclab_binary), operation, "-t", str(lab.path)),
            environment=environment,
            cwd=lab.path.parent,
            peer_uid=peer.uid,
            peer_pid=peer.pid,
        )
        return {"job": job.public()}

    def _lab_environment(
        self, lab_id: object, profile_name: object, overrides: object
    ) -> tuple[Lab, dict[str, Any], dict[str, str]]:
        lab = self._catalog.resolve(lab_id)
        document = self._catalog.load_document(lab)
        profile = self._profile(profile_name)
        caller = sanitize_caller_overrides(overrides, secret_names=profile.secret_names)
        reject_license_source_overrides(document, caller)
        reject_vrnetlab_source_overrides(
            document, caller, lab_name=topology_name(document, lab.path)
        )
        return lab, document, self._invocation_environment(profile, caller)

    def _profile(self, value: object) -> Profile:
        if value is None:
            return self._config.profile(None)
        if not isinstance(value, str):
            raise RequestError("profile must be a configured profile name")
        return self._config.profile(value)

    def _base_environment(self) -> dict[str, str]:
        return {
            "PATH": self._config.runtime_path,
            "HOME": str(self._config.state_dir),
            "XDG_STATE_HOME": str(self._config.state_dir),
            "XDG_CACHE_HOME": str(self._config.state_dir / "cache"),
            "XDG_CONFIG_HOME": str(self._config.state_dir / "config"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "USER": "root",
            "LOGNAME": "root",
            "CONTAINERLAB_BIN": str(self._config.containerlab_binary),
        }

    def _invocation_environment(self, profile: Profile, overrides: Mapping[str, str]) -> dict[str, str]:
        environment = dict(profile.environment)
        environment.update(profile.secrets)
        environment.update(overrides)
        # Service-controlled values are applied last and cannot be influenced by
        # either caller overrides or accidental inherited daemon environment.
        environment.update(self._base_environment())
        return environment

    async def _inspect(self, lab: Lab, environment: Mapping[str, str]) -> Mapping[str, object] | None:
        capture = await self._capture(
            (str(self._config.eclab_binary), "inspect", "-t", str(lab.path), "--format", "json"),
            environment,
            cwd=lab.path.parent,
        )
        if capture.timed_out or capture.returncode != 0 or capture.stdout_truncated:
            return None
        try:
            value = json.loads(capture.stdout)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, Mapping) else None

    @staticmethod
    def _normalize_inspection(inspection: Mapping[str, object]) -> list[dict[str, str | None]]:
        nodes: list[dict[str, str | None]] = []
        for entries in inspection.values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, Mapping):
                    continue
                name = entry.get("name")
                if not isinstance(name, str) or not name:
                    continue
                state = entry.get("state")
                status = entry.get("status")
                nodes.append(
                    {
                        "container": name.lstrip("/"),
                        "state": state.lower() if isinstance(state, str) else None,
                        "status": status.lower() if isinstance(status, str) else None,
                    }
                )
        return sorted(nodes, key=lambda item: item["container"] or "")

    @staticmethod
    def _container_for_node(
        inspection: Mapping[str, object], *, node: str, expected_lab_name: str
    ) -> str:
        containers = [
            item["container"]
            for item in LabOperations._normalize_inspection(inspection)
            if isinstance(item.get("container"), str)
        ]
        expected = f"clab-{expected_lab_name}-{node}"
        if expected in containers:
            return expected
        matches = [
            container
            for container in containers
            if container.startswith("clab-") and container.endswith(f"-{node}")
        ]
        if len(matches) != 1:
            raise OperationError("could not map the selected topology node to one running container")
        return matches[0]

    async def _capture(
        self, argv: Sequence[str], environment: Mapping[str, str], *, cwd: Path
    ) -> Capture:
        """Run a fixed command without a shell while draining bounded output streams."""
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(cwd),
                env=dict(environment),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except OSError:
            return Capture(127, b"", b"", False, False, False)
        assert process.stdout is not None
        assert process.stderr is not None
        stdout_task = asyncio.create_task(self._read_limited(process.stdout))
        stderr_task = asyncio.create_task(self._read_limited(process.stderr))
        timed_out = False
        try:
            await asyncio.wait_for(process.wait(), timeout=self._config.read_timeout_seconds)
        except TimeoutError:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                process.kill()
            await process.wait()
        stdout, stdout_truncated = await stdout_task
        stderr, stderr_truncated = await stderr_task
        return Capture(
            process.returncode if process.returncode is not None else 127,
            stdout,
            stderr,
            stdout_truncated,
            stderr_truncated,
            timed_out,
        )

    async def _read_limited(self, stream: asyncio.StreamReader) -> tuple[bytes, bool]:
        buffer = bytearray()
        truncated = False
        while chunk := await stream.read(64 * 1024):
            remaining = self._config.max_read_output_bytes - len(buffer)
            if remaining > 0:
                buffer.extend(chunk[:remaining])
            if len(chunk) > remaining:
                truncated = True
        return bytes(buffer), truncated

    def _public_text(self, value: bytes) -> str:
        return value[-self._response_text_limit :].decode("utf-8", errors="replace")

    def _first_line(self, value: bytes) -> str | None:
        text = self._public_text(value).strip()
        return text.splitlines()[0] if text else None
