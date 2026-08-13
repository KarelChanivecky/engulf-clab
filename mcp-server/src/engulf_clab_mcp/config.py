"""Root-owned configuration for the local privileged eclab service."""

from __future__ import annotations

import os
import stat
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .errors import ConfigurationError, NotFoundError
from .security import validate_environment_mapping

DEFAULT_CONFIG_PATH = Path("/etc/eclab-mcp/config.toml")
_IDENTIFIER = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"


@dataclass(frozen=True, slots=True)
class LabRoot:
    """One administrator-approved root for discoverable topology files."""

    identifier: str
    path: Path


@dataclass(frozen=True, slots=True)
class Profile:
    """Root-owned default and secret environment for one lab invocation profile."""

    name: str
    environment: Mapping[str, str]
    secrets: Mapping[str, str]

    @property
    def secret_names(self) -> frozenset[str]:
        return frozenset(self.secrets)


@dataclass(frozen=True, slots=True)
class ServiceConfig:
    """All normalized daemon configuration values."""

    socket_path: Path
    socket_group: str
    eclab_binary: Path
    containerlab_binary: Path
    docker_binary: Path
    state_dir: Path
    log_dir: Path
    runtime_path: str
    lab_roots: Mapping[str, LabRoot]
    profiles: Mapping[str, Profile]
    job_retention_days: int
    max_job_log_bytes: int
    max_rpc_frame_bytes: int
    max_read_output_bytes: int
    read_timeout_seconds: float
    cancel_grace_seconds: float

    def profile(self, name: str | None) -> Profile:
        """Resolve an explicit profile or the conventional default profile."""
        selected = "default" if name is None or not name else name
        profile = self.profiles.get(selected)
        if profile is None:
            raise NotFoundError(f"profile {selected!r} is not configured")
        return profile


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> ServiceConfig:
    """Load and validate a root-owned TOML service configuration."""
    configured_path = path.expanduser()
    if not configured_path.is_absolute():
        raise ConfigurationError("service configuration path must be absolute")
    _verify_config_file(configured_path)
    try:
        config_path = configured_path.resolve(strict=True)
    except OSError as error:
        raise ConfigurationError("service configuration is unavailable") from error
    try:
        with config_path.open("rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigurationError(f"could not read service configuration: {error}") from error
    if not isinstance(raw, Mapping):
        raise ConfigurationError("service configuration must be a TOML mapping")
    service = _mapping(raw.get("service"), "[service]")

    socket_path = _path(service, "socket_path", "/run/eclab-mcp/eclab-mcp.sock")
    socket_group = _identifier(service.get("socket_group", "eclab-mcp"), "service.socket_group")
    eclab_binary = _executable_path(service, "eclab_binary")
    containerlab_binary = _executable_path(service, "containerlab_binary")
    docker_binary = _executable_path(service, "docker_binary")
    state_dir = _path(service, "state_dir", "/var/lib/eclab-mcp")
    log_dir = _path(service, "log_dir", "/var/log/eclab-mcp")
    runtime_path = _string(
        service.get("runtime_path", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"),
        "service.runtime_path",
    )
    if not runtime_path or "\x00" in runtime_path:
        raise ConfigurationError("service.runtime_path must be a nonempty text path")

    roots = _roots(raw.get("lab_roots"))
    profiles = _profiles(raw.get("profiles", {}))
    if not profiles:
        raise ConfigurationError("at least one profile must be configured")

    return ServiceConfig(
        socket_path=socket_path,
        socket_group=socket_group,
        eclab_binary=eclab_binary,
        containerlab_binary=containerlab_binary,
        docker_binary=docker_binary,
        state_dir=state_dir,
        log_dir=log_dir,
        runtime_path=runtime_path,
        lab_roots=MappingProxyType(roots),
        profiles=MappingProxyType(profiles),
        job_retention_days=_integer(service.get("job_retention_days", 14), "job_retention_days", 1, 3650),
        max_job_log_bytes=_integer(
            service.get("max_job_log_bytes", 2 * 1024 * 1024),
            "max_job_log_bytes",
            64 * 1024,
            64 * 1024 * 1024,
        ),
        max_rpc_frame_bytes=_integer(
            service.get("max_rpc_frame_bytes", 64 * 1024),
            "max_rpc_frame_bytes",
            1024,
            1024 * 1024,
        ),
        max_read_output_bytes=_integer(
            service.get("max_read_output_bytes", 64 * 1024),
            "max_read_output_bytes",
            4096,
            4 * 1024 * 1024,
        ),
        read_timeout_seconds=_number(
            service.get("read_timeout_seconds", 30), "read_timeout_seconds", 1, 600
        ),
        cancel_grace_seconds=_number(
            service.get("cancel_grace_seconds", 10), "cancel_grace_seconds", 1, 60
        ),
    )


def _verify_config_file(path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise ConfigurationError(f"service configuration is unavailable: {path}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ConfigurationError("service configuration must be a regular non-symlink file")
    if os.geteuid() == 0:
        if metadata.st_uid != 0:
            raise ConfigurationError("root daemon configuration must be owned by root")
        if metadata.st_mode & 0o077:
            raise ConfigurationError("root daemon configuration must be private (mode 0600)")


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ConfigurationError(f"{label} must be a TOML table")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ConfigurationError(f"{label} must be a string")
    return value


def _identifier(value: object, label: str) -> str:
    text = _string(value, label)
    if not text or len(text) > 64 or any(character not in _IDENTIFIER for character in text):
        raise ConfigurationError(f"{label} must use letters, digits, underscores, or hyphens")
    return text


def _path(mapping: Mapping[str, Any], key: str, default: str | None = None) -> Path:
    value = mapping.get(key, default)
    if not isinstance(value, str) or not value:
        raise ConfigurationError(f"service.{key} must be a nonempty absolute path")
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        raise ConfigurationError(f"service.{key} must be an absolute path")
    return candidate.resolve(strict=False)


def _executable_path(mapping: Mapping[str, Any], key: str) -> Path:
    path = _path(mapping, key)
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ConfigurationError(f"service.{key} must name an executable file")
    return path.resolve()


def _roots(value: object) -> dict[str, LabRoot]:
    if not isinstance(value, list) or not value:
        raise ConfigurationError("at least one [[lab_roots]] entry is required")
    result: dict[str, LabRoot] = {}
    for item in value:
        entry = _mapping(item, "[[lab_roots]]")
        identifier = _identifier(entry.get("id"), "lab_roots.id")
        raw_path = entry.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            raise ConfigurationError("lab_roots.path must be a nonempty absolute path")
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            raise ConfigurationError("lab_roots.path must be an absolute path")
        try:
            if path.is_symlink():
                raise ConfigurationError("lab_roots.path must not be a symlink")
            resolved = path.resolve(strict=True)
        except OSError as error:
            raise ConfigurationError(f"lab root does not exist: {path}") from error
        if not resolved.is_dir():
            raise ConfigurationError(f"lab root must be a directory: {path}")
        if identifier in result:
            raise ConfigurationError(f"duplicate lab root ID: {identifier}")
        result[identifier] = LabRoot(identifier=identifier, path=resolved)
    return result


def _profiles(value: object) -> dict[str, Profile]:
    mapping = _mapping(value, "[profiles]")
    result: dict[str, Profile] = {}
    for name, raw_profile in mapping.items():
        identifier = _identifier(name, "profile name")
        profile = _mapping(raw_profile, f"[profiles.{identifier}]")
        environment = validate_environment_mapping(
            profile.get("environment", {}),
            owner=f"profiles.{identifier}.environment",
            error_type=ConfigurationError,
        )
        secrets = validate_environment_mapping(
            profile.get("secrets", {}),
            owner=f"profiles.{identifier}.secrets",
            error_type=ConfigurationError,
        )
        if set(environment) & set(secrets):
            raise ConfigurationError(f"profile {identifier} defines an environment key as both normal and secret")
        result[identifier] = Profile(
            name=identifier,
            environment=MappingProxyType(environment),
            secrets=MappingProxyType(secrets),
        )
    return result


def _integer(value: object, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ConfigurationError(f"service.{label} must be an integer between {minimum} and {maximum}")
    return value


def _number(value: object, label: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigurationError(f"service.{label} must be a number")
    numeric = float(value)
    if not minimum <= numeric <= maximum:
        raise ConfigurationError(f"service.{label} must be between {minimum:g} and {maximum:g}")
    return numeric
