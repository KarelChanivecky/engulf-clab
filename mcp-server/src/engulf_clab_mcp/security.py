"""Validation and environment isolation for requests crossing the root boundary."""

from __future__ import annotations

import re
from collections.abc import Mapping

from .errors import ConfigurationError, RequestError

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_MAX_ENV_VALUE_BYTES = 4096
_PROTECTED_EXACT = frozenset(
    {
        "PATH",
        "HOME",
        "SHELL",
        "PWD",
        "OLDPWD",
        "TMPDIR",
        "TMP",
        "TEMP",
        "IFS",
        "ENV",
        "BASH_ENV",
        "SHELLOPTS",
        "CDPATH",
        "GOMOD",
        "GOWORK",
        "ECLAB_VM_IMG",
        "ECLAB_VM_SRC",
        "ECLAB_VRNETLAB_IMG_PATH",
    }
)
_PROTECTED_PREFIXES = (
    "PYTHON",
    "LD_",
    "DYLD_",
    "XDG_",
    "ENGULF_",
    "CONTAINERLAB_",
    "VRNETLAB_",
    "ECLAB_MCP_",
    "ECLAB_LICENSE",
    "GIT_",
    "SSH_",
    "DOCKER_",
    "BUILDKIT_",
    "COMPOSE_",
    "BASH_",
    "SUDO_",
    "SYSTEMD_",
    "PIP_",
    "UV_",
    "NIX_",
    "CONDA_",
    "VIRTUAL_ENV",
    "PERL",
    "RUBY",
    "NODE_",
    "JAVA_",
    "GOPATH",
    "GOENV",
    "GOCACHE",
    "RUST",
)
_VARIABLE_REFERENCE = re.compile(r"^\$(?:([A-Za-z_][A-Za-z0-9_]*)|\{([A-Za-z_][A-Za-z0-9_]*)\})$")
_NON_ALPHANUMERIC = re.compile(r"[^A-Z0-9]+")


def is_protected_environment_name(name: str) -> bool:
    """Return whether a caller must never control this process environment key."""
    return name in _PROTECTED_EXACT or name.startswith(_PROTECTED_PREFIXES)


def validate_environment_mapping(
    value: object,
    *,
    owner: str,
    error_type: type[ConfigurationError | RequestError],
) -> dict[str, str]:
    """Validate textual key/value pairs without putting values into error messages."""
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise error_type(f"{owner} must be a mapping of environment variable names to strings")
    validated: dict[str, str] = {}
    for name, item in value.items():
        assert isinstance(name, str)
        if _ENV_NAME.fullmatch(name) is None:
            raise error_type(f"{owner} contains an invalid environment variable name")
        if not isinstance(item, str):
            raise error_type(f"{owner}.{name} must be a string")
        if len(item.encode("utf-8")) > _MAX_ENV_VALUE_BYTES:
            raise error_type(f"{owner}.{name} exceeds the maximum environment value length")
        if any(ord(character) < 32 or ord(character) == 127 for character in item):
            raise error_type(f"{owner}.{name} contains a control character")
        validated[name] = item
    return validated


def sanitize_caller_overrides(value: object, *, secret_names: frozenset[str]) -> dict[str, str]:
    """Accept non-secret application variables while retaining daemon process control."""
    if value is None:
        return {}
    overrides = validate_environment_mapping(
        value, owner="environment", error_type=RequestError
    )
    for name in overrides:
        if name in secret_names:
            raise RequestError(f"environment variable {name} is profile-owned and cannot be overridden")
        if is_protected_environment_name(name):
            raise RequestError(f"environment variable {name} is controlled by the service")
    return overrides


def reject_license_source_overrides(document: Mapping[str, object], overrides: Mapping[str, str]) -> None:
    """Prevent caller values from selecting root-readable license sources.

    License pools name their environment variable in the topology itself, so the
    normal protected-name list cannot know those names in advance.
    """
    topology = document.get("topology")
    nodes = topology.get("nodes") if isinstance(topology, Mapping) else None
    if not isinstance(nodes, Mapping):
        return
    for node in nodes.values():
        if not isinstance(node, Mapping):
            continue
        license_value = node.get("license")
        if not isinstance(license_value, str) or not license_value.startswith("$"):
            continue
        pool_name = license_value[1:]
        if pool_name and pool_name in overrides:
            raise RequestError(
                f"license pool variable {pool_name} must be configured in the selected profile"
            )


def reject_vrnetlab_source_overrides(
    document: Mapping[str, object], overrides: Mapping[str, str], *, lab_name: str
) -> None:
    """Keep caller variables away from topology-declared root-readable VM inputs."""
    topology = document.get("topology")
    nodes = topology.get("nodes") if isinstance(topology, Mapping) else None
    if not isinstance(nodes, Mapping):
        return
    normalized_lab = _normalize_component(lab_name)
    for node_name, node in nodes.items():
        if not isinstance(node_name, str) or not isinstance(node, Mapping):
            continue
        environment = node.get("env")
        if not isinstance(environment, Mapping):
            continue
        for key, value in environment.items():
            if not isinstance(key, str) or not isinstance(value, str):
                continue
            if key not in {"ECLAB_VM_IMG", "ECLAB_VM_SRC"} and not key.endswith(
                "VRNETLAB_IMG_PATH"
            ):
                continue
            match = _VARIABLE_REFERENCE.fullmatch(value.strip())
            if match is None:
                continue
            variable = match.group(1) or match.group(2)
            assert variable is not None
            candidates = (
                f"{normalized_lab}_{_normalize_component(node_name)}_{_normalize_component(variable)}",
                f"{normalized_lab}_{_normalize_component(variable)}",
                variable,
            )
            if any(candidate in overrides for candidate in candidates):
                raise RequestError(
                    "vrnetlab image source variables must be configured in the selected profile"
                )


def _normalize_component(value: str) -> str:
    normalized = _NON_ALPHANUMERIC.sub("_", value.upper()).strip("_")
    return normalized or "INVALID"
