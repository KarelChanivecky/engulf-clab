"""Unprivileged standard-stdio MCP bridge for the root local Unix daemon."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .protocol import PROTOCOL_VERSION

DEFAULT_SOCKET_PATH = Path("/run/eclab-mcp/eclab-mcp.sock")
_MAX_RESPONSE_BYTES = 1024 * 1024


class UnixRpcClient:
    """A one-request-per-connection client for the private, bounded socket RPC."""

    def __init__(self, socket_path: Path, *, timeout_seconds: float = 30) -> None:
        self._socket_path = socket_path
        self._timeout_seconds = timeout_seconds

    async def call(self, method: str, params: Mapping[str, object]) -> dict[str, object]:
        """Return a structured service result without leaking bridge exceptions to MCP."""
        request_id = uuid.uuid4().hex
        payload = {
            "version": PROTOCOL_VERSION,
            "id": request_id,
            "method": method,
            "params": dict(params),
        }
        try:
            encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(str(self._socket_path), limit=_MAX_RESPONSE_BYTES),
                timeout=self._timeout_seconds,
            )
            try:
                writer.write(encoded + b"\n")
                await writer.drain()
                line = await asyncio.wait_for(reader.readline(), timeout=self._timeout_seconds)
            finally:
                writer.close()
                await writer.wait_closed()
        except (ConnectionError, OSError, TimeoutError):
            return {
                "ok": False,
                "error": {
                    "code": "service_unavailable",
                    "message": "the local eclab MCP service is unavailable",
                },
            }
        if not line or len(line) > _MAX_RESPONSE_BYTES:
            return _bridge_error("invalid_response", "the local eclab MCP service returned an invalid response")
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _bridge_error("invalid_response", "the local eclab MCP service returned invalid JSON")
        if not isinstance(value, Mapping) or value.get("version") != PROTOCOL_VERSION:
            return _bridge_error("invalid_response", "the local eclab MCP service returned an invalid response")
        if value.get("id") != request_id or not isinstance(value.get("ok"), bool):
            return _bridge_error("invalid_response", "the local eclab MCP service returned an invalid response")
        if value["ok"]:
            result = value.get("result")
            if isinstance(result, Mapping):
                return {"ok": True, "result": dict(result)}
        error = value.get("error")
        if isinstance(error, Mapping):
            code = error.get("code")
            message = error.get("message")
            if isinstance(code, str) and isinstance(message, str):
                result: dict[str, object] = {"ok": False, "error": {"code": code, "message": message}}
                active_job = error.get("active_job_id")
                if isinstance(active_job, str):
                    result["error"] = {
                        "code": code,
                        "message": message,
                        "active_job_id": active_job,
                    }
                return result
        return _bridge_error("invalid_response", "the local eclab MCP service returned an invalid response")


def _bridge_error(code: str, message: str) -> dict[str, object]:
    return {"ok": False, "error": {"code": code, "message": message}}


def create_server(socket_path: Path) -> Any:
    """Create the SDK-backed stdio MCP server only when the bridge is launched."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as error:  # Allows package tests without importing optional runtime code.
        raise RuntimeError("eclab-mcp requires the 'mcp' Python package") from error

    client = UnixRpcClient(socket_path)
    server = FastMCP("eclab")

    @server.tool()
    async def eclab_list_labs() -> dict[str, object]:
        """Discover permitted labs and named invocation profiles on this machine."""
        return await client.call("labs.list", {})

    @server.tool()
    async def eclab_validate(lab_id: str) -> dict[str, object]:
        """Parse one discovered lab and run a read-only offline Containerlab validation."""
        return await client.call("lab.validate", {"lab_id": lab_id})

    @server.tool()
    async def eclab_deploy(
        lab_id: str,
        profile: str = "default",
        environment: dict[str, str] | None = None,
    ) -> dict[str, object]:
        """Queue whole-lab deployment; returns a job ID to inspect rather than blocking."""
        return await client.call(
            "lab.deploy",
            {"lab_id": lab_id, "profile": profile, "environment": environment or {}},
        )

    @server.tool()
    async def eclab_destroy(
        lab_id: str,
        profile: str = "default",
        environment: dict[str, str] | None = None,
    ) -> dict[str, object]:
        """Queue destruction of exactly one discovered lab; destroy-all is never available."""
        return await client.call(
            "lab.destroy",
            {"lab_id": lab_id, "profile": profile, "environment": environment or {}},
        )

    @server.tool()
    async def eclab_status(
        lab_id: str,
        profile: str = "default",
        environment: dict[str, str] | None = None,
    ) -> dict[str, object]:
        """Return normalized Containerlab node state and health status for one lab."""
        return await client.call(
            "lab.status",
            {"lab_id": lab_id, "profile": profile, "environment": environment or {}},
        )

    @server.tool()
    async def eclab_node_logs(
        lab_id: str,
        node: str,
        tail_lines: int = 200,
        profile: str = "default",
        environment: dict[str, str] | None = None,
    ) -> dict[str, object]:
        """Return a bounded tail of Docker logs for a node declared by one discovered lab."""
        return await client.call(
            "lab.node_logs",
            {
                "lab_id": lab_id,
                "node": node,
                "tail_lines": tail_lines,
                "profile": profile,
                "environment": environment or {},
            },
        )

    @server.tool()
    async def eclab_diagnostics(
        lab_id: str | None = None,
        profile: str = "default",
        environment: dict[str, str] | None = None,
    ) -> dict[str, object]:
        """Return bounded tool versions, installed eclab plugin diagnostics, and optional lab status."""
        return await client.call(
            "lab.diagnostics",
            {"lab_id": lab_id, "profile": profile, "environment": environment or {}},
        )

    @server.tool()
    async def eclab_job_status(job_id: str) -> dict[str, object]:
        """Return the lifecycle state of a previously queued eclab job."""
        return await client.call("job.status", {"job_id": job_id})

    @server.tool()
    async def eclab_list_jobs(limit: int = 20) -> dict[str, object]:
        """List up to 100 retained lifecycle jobs, newest first."""
        return await client.call("job.list", {"limit": limit})

    @server.tool()
    async def eclab_job_logs(job_id: str, tail_lines: int = 200) -> dict[str, object]:
        """Return a bounded tail of a job's root-owned eclab output log."""
        return await client.call("job.logs", {"job_id": job_id, "tail_lines": tail_lines})

    @server.tool()
    async def eclab_job_cancel(job_id: str) -> dict[str, object]:
        """Request termination of the known job process group; no arbitrary process IDs are accepted."""
        return await client.call("job.cancel", {"job_id": job_id})

    return server


def main(argv: list[str] | None = None) -> int:
    """Run the unprivileged stdio bridge expected by standard local MCP clients."""
    parser = argparse.ArgumentParser(prog="eclab-mcp")
    parser.add_argument("--socket", default=str(DEFAULT_SOCKET_PATH), metavar="PATH")
    arguments = parser.parse_args(argv)
    socket_path = Path(arguments.socket).expanduser()
    if not socket_path.is_absolute():
        print("eclab-mcp: --socket must be an absolute path", file=sys.stderr)
        return 2
    try:
        server = create_server(socket_path)
    except RuntimeError as error:
        print(f"eclab-mcp: {error}", file=sys.stderr)
        return 1
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
