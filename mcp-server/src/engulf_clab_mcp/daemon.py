"""Root-owned Unix-socket executor for the local eclab MCP bridge."""

from __future__ import annotations

import argparse
import asyncio
import grp
import logging
import os
import signal
import socket
import stat
import struct
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .config import DEFAULT_CONFIG_PATH, ServiceConfig, load_config
from .errors import BusyError, ConfigurationError, McpServiceError, RequestError
from .jobs import Job, JobManager
from .labs import LabCatalog
from .operations import LabOperations, PeerIdentity
from .protocol import read_request, response_error, response_ok, write_response

_LOGGER = logging.getLogger("engulf_clab_mcp.daemon")


class LocalDaemon:
    """Serve only the fixed private RPC methods over one protected Unix socket."""

    def __init__(self, config: ServiceConfig) -> None:
        self._config = config
        self._catalog = LabCatalog(config)
        self._jobs = JobManager(
            state_dir=config.state_dir,
            log_dir=config.log_dir,
            max_log_bytes=config.max_job_log_bytes,
            max_read_bytes=config.max_read_output_bytes,
            retention_days=config.job_retention_days,
            cancel_grace_seconds=config.cancel_grace_seconds,
            audit=self._audit_job,
        )
        self._operations = LabOperations(config, self._catalog, self._jobs)
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        """Create secure daemon directories, recover jobs, and bind the socket."""
        _ensure_private_directory(self._config.state_dir, "state directory")
        _ensure_private_directory(self._config.log_dir, "log directory")
        _ensure_private_directory(self._config.socket_path.parent, "socket directory")
        await self._jobs.start()
        self._remove_stale_socket()
        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(self._config.socket_path),
            limit=self._config.max_rpc_frame_bytes,
        )
        self._set_socket_permissions()
        _LOGGER.info("listening on the protected local eclab MCP socket")

    async def run(self, stop: asyncio.Event) -> None:
        """Run until the service process receives a termination signal."""
        await self.start()
        await stop.wait()
        await self.close()

    async def close(self) -> None:
        """Stop new clients, cancel owned jobs, and remove only our socket file."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        await self._jobs.close()
        try:
            metadata = self._config.socket_path.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISSOCK(metadata.st_mode):
            self._config.socket_path.unlink()

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = _peer_identity(writer)
        try:
            while True:
                request_id = "unknown"
                try:
                    request = await read_request(
                        reader, max_bytes=self._config.max_rpc_frame_bytes
                    )
                    if request is None:
                        return
                    request_id = request.request_id
                    _LOGGER.info(
                        "RPC request method=%s peer_uid=%s peer_pid=%s",
                        request.method,
                        peer.uid,
                        peer.pid,
                    )
                    result = await self._dispatch(request.method, request.params, peer)
                    response = response_ok(request_id, result)
                except BusyError as error:
                    response = response_error(
                        request_id,
                        error.code,
                        error.message,
                        active_job_id=error.job_id,
                    )
                except McpServiceError as error:
                    response = response_error(request_id, error.code, error.message)
                except Exception:  # noqa: BLE001 - a daemon boundary must return a safe protocol error.
                    # Do not include exception text: a child tool or profile value
                    # must never leak through a privileged protocol error or journal.
                    _LOGGER.error("unexpected local RPC failure for peer_uid=%s", peer.uid)
                    response = response_error(
                        request_id, "operation_failed", "the service could not complete the request"
                    )
                await write_response(
                    writer, response, max_bytes=self._config.max_rpc_frame_bytes
                )
        except (ConnectionError, asyncio.IncompleteReadError):
            return
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass

    async def _dispatch(
        self, method: str, params: Mapping[str, Any], peer: PeerIdentity
    ) -> dict[str, object]:
        if method == "labs.list":
            _only(params)
            return await self._operations.list_labs()
        if method == "lab.validate":
            _only(params, "lab_id")
            return await self._operations.validate(params.get("lab_id"))
        if method == "lab.deploy":
            _only(params, "lab_id", "profile", "environment")
            return await self._operations.deploy(
                params.get("lab_id"), params.get("profile"), params.get("environment"), peer
            )
        if method == "lab.destroy":
            _only(params, "lab_id", "profile", "environment")
            return await self._operations.destroy(
                params.get("lab_id"), params.get("profile"), params.get("environment"), peer
            )
        if method == "lab.status":
            _only(params, "lab_id", "profile", "environment")
            return await self._operations.status(
                params.get("lab_id"), params.get("profile"), params.get("environment")
            )
        if method == "lab.node_logs":
            _only(params, "lab_id", "node", "tail_lines", "profile", "environment")
            return await self._operations.node_logs(
                params.get("lab_id"),
                params.get("node"),
                params.get("tail_lines", 200),
                params.get("profile"),
                params.get("environment"),
            )
        if method == "lab.diagnostics":
            _only(params, "lab_id", "profile", "environment")
            return await self._operations.diagnostics(
                params.get("lab_id"), params.get("profile"), params.get("environment")
            )
        if method == "job.status":
            _only(params, "job_id")
            return {"job": self._jobs.status(params.get("job_id")).public()}
        if method == "job.list":
            _only(params, "limit")
            return {"jobs": [job.public() for job in self._jobs.list(params.get("limit", 20))]}
        if method == "job.logs":
            _only(params, "job_id", "tail_lines")
            return self._jobs.logs(params.get("job_id"), params.get("tail_lines", 200))
        if method == "job.cancel":
            _only(params, "job_id")
            return {"job": (await self._jobs.cancel(params.get("job_id"))).public()}
        raise RequestError("unknown RPC method")

    def _remove_stale_socket(self) -> None:
        path = self._config.socket_path
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            return
        if not stat.S_ISSOCK(metadata.st_mode):
            raise ConfigurationError("configured socket path exists and is not a Unix socket")
        path.unlink()

    def _set_socket_permissions(self) -> None:
        path = self._config.socket_path
        if os.geteuid() == 0:
            try:
                group = grp.getgrnam(self._config.socket_group)
            except KeyError as error:
                raise ConfigurationError(
                    f"configured socket group does not exist: {self._config.socket_group}"
                ) from error
            os.chown(path, 0, group.gr_gid)
            os.chmod(path, 0o660)
        else:
            # This makes foreground development possible but is intentionally not
            # a supported privileged installation mode.
            os.chmod(path, 0o600)

    @staticmethod
    def _audit_job(event: str, job: Job) -> None:
        _LOGGER.info(
            "%s job_id=%s operation=%s lab_id=%s profile=%s state=%s peer_uid=%s peer_pid=%s",
            event,
            job.identifier,
            job.operation,
            job.lab_id,
            job.profile,
            job.state,
            job.peer_uid,
            job.peer_pid,
        )


def _only(params: Mapping[str, Any], *allowed: str) -> None:
    unknown = set(params) - set(allowed)
    if unknown:
        raise RequestError("request contains unsupported parameters")


def _peer_identity(writer: asyncio.StreamWriter) -> PeerIdentity:
    socket_value = writer.get_extra_info("socket")
    if socket_value is None or not hasattr(socket_value, "getsockopt") or not hasattr(socket, "SO_PEERCRED"):
        return PeerIdentity(uid=None, pid=None, gid=None)
    try:
        raw = socket_value.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        pid, uid, gid = struct.unpack("3i", raw)
    except OSError:
        return PeerIdentity(uid=None, pid=None, gid=None)
    return PeerIdentity(uid=uid, pid=pid, gid=gid)


def _ensure_private_directory(path: Path, label: str) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        metadata = path.lstat()
    except OSError as error:
        raise ConfigurationError(f"{label} is unavailable") from error
    if path.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
        raise ConfigurationError(f"{label} must be a real directory")
    if os.geteuid() == 0:
        if metadata.st_uid != 0:
            raise ConfigurationError(f"{label} must be owned by root")
        if metadata.st_mode & 0o022:
            raise ConfigurationError(f"{label} must not be group- or world-writable")


async def _run(config: ServiceConfig) -> None:
    daemon = LocalDaemon(config)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_value in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_value, stop.set)
        except NotImplementedError:
            pass
    await daemon.run(stop)


def main(argv: list[str] | None = None) -> int:
    """Run the root daemon in the foreground for systemd supervision."""
    parser = argparse.ArgumentParser(prog="eclab-mcpd")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), metavar="PATH")
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="validate the root-owned configuration and exit without binding the socket",
    )
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s: %(message)s")
    if os.geteuid() != 0:
        _LOGGER.error("eclab-mcpd must run as root under systemd")
        return 2
    try:
        config = load_config(Path(arguments.config))
        if arguments.check_config:
            _LOGGER.info("configuration is valid")
            return 0
        asyncio.run(_run(config))
    except McpServiceError as error:
        _LOGGER.error("%s", error.message)
        return 1
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
