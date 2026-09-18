"""Construct commands for individual privileged children, without elevating callers."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

__all__ = [
    "docker_command",
    "docker_environment",
    "docker_needs_sudo",
    "require_root_access",
    "root_command",
]

_DOCKER_ENV = (
    "DOCKER_HOST",
    "DOCKER_CONTEXT",
    "DOCKER_CONFIG",
    "DOCKER_TLS_VERIFY",
    "DOCKER_CERT_PATH",
    "DOCKER_API_VERSION",
    "DOCKER_BUILDKIT",
    "BUILDX_BUILDER",
    "SSH_AUTH_SOCK",
)


def _executable(command: str) -> str:
    found = shutil.which(command)
    if found is None:
        raise FileNotFoundError(f"missing required command: {command}")
    # Do not resolve interpreter symlinks: a venv must keep its installed packages.
    return os.path.abspath(found)


def root_command(
    argv: Sequence[str],
    *,
    non_interactive: bool = False,
    background: bool = False,
    preserve_env: Sequence[str] = (),
) -> list[str]:
    """Use sudo for a known privileged operation unless already running as root."""
    if os.name != "posix" or os.geteuid() == 0:
        return list(argv)
    command = [_executable("sudo")]
    if non_interactive:
        command.append("-n")
    if background:
        command.append("-b")
    if preserve_env:
        command.append("--preserve-env=" + ",".join(preserve_env))
    return [*command, "--", _executable(argv[0]), *argv[1:]]


def require_root_access() -> None:
    """Authenticate on the caller's terminal before detached or parallel host work."""
    if os.name == "posix" and os.geteuid() != 0:
        subprocess.run([_executable("sudo"), "-v"], check=True)


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _docker_selection(environment: Mapping[str, str]) -> tuple[Path, str | None]:
    config = Path(environment.get("DOCKER_CONFIG") or Path.home() / ".docker").absolute()
    context = environment.get("DOCKER_CONTEXT")
    host = environment.get("DOCKER_HOST")
    if not context and host:
        return config, host
    if not context:
        context = _object(config / "config.json").get("currentContext")
    if not context or context == "default":
        return config, host or "unix:///var/run/docker.sock"
    # Docker stores named contexts locally; discovering one needs no daemon access.
    for path in (config / "contexts" / "meta").glob("*/meta.json"):
        metadata = _object(path)
        if metadata.get("Name") != context:
            continue
        endpoints = metadata.get("Endpoints")
        endpoint = endpoints.get("docker") if isinstance(endpoints, dict) else None
        host = endpoint.get("Host") if isinstance(endpoint, dict) else None
        return config, host if isinstance(host, str) else None
    # Leave invalid/unknown contexts to Docker; never switch to root's default daemon.
    return config, None


def docker_needs_sudo() -> bool:
    """Escalate only for a selected local Unix socket the caller cannot access."""
    if os.name != "posix" or os.geteuid() == 0:
        return False
    _, host = _docker_selection(os.environ)
    if host is None or not host.startswith("unix://"):
        return False
    path = host.removeprefix("unix://")
    try:
        metadata = os.stat(path)
    except FileNotFoundError:
        return False
    except PermissionError:
        return True
    return stat.S_ISSOCK(metadata.st_mode) and not os.access(path, os.W_OK)


def docker_command(argv: Sequence[str]) -> Sequence[str]:
    """Keep Docker selection/credentials when sudo is needed for its local socket."""
    if not docker_needs_sudo():
        return argv
    config, _ = _docker_selection(os.environ)
    return root_command(
        [argv[0], "--config", str(config), *argv[1:]],
        preserve_env=[key for key in _DOCKER_ENV if key in os.environ],
    )


@contextmanager
def docker_environment() -> Iterator[dict[str, str] | None]:
    """Let unprivileged Make recipes invoke the same sudo-aware Docker command."""
    command = docker_command(("docker",))
    if command == ("docker",):
        yield None
        return
    require_root_access()
    with tempfile.TemporaryDirectory(prefix="engulf-docker-") as directory:
        shim = Path(directory) / "docker"
        shim.write_text("#!/bin/sh\nexec " + shlex.join(command) + ' "$@"\n', encoding="utf-8")
        shim.chmod(0o700)
        environment = dict(os.environ)
        environment["PATH"] = directory + os.pathsep + environment.get("PATH", os.defpath)
        yield environment
