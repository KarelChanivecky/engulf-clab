from __future__ import annotations

import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engulf_api import ApplicationMetadata

from .errors import DockerfileError
from .topology import topology_nodes

_NON_ALPHANUMERIC = re.compile(r"[^A-Z0-9]+")
_RESERVED_ARGUMENTS = frozenset(("-f", "--file", "-t", "--tag"))


@dataclass(frozen=True)
class BuildRequest:
    node_name: str
    image: str
    dockerfile: Path
    context: Path
    build_args: tuple[tuple[str, str], ...]
    extra_args: tuple[str, ...]


def environment_prefix(application_name: str) -> str:
    prefix = _NON_ALPHANUMERIC.sub("_", application_name.upper()).strip("_")
    if not prefix:
        raise DockerfileError(f"cannot derive environment prefix from {application_name!r}")
    return prefix


def application_prefix_name(application: ApplicationMetadata) -> str:
    """Select short product metadata, falling back to the full product name."""
    short_name = getattr(application, "short_product_name", None)
    if isinstance(short_name, str) and short_name.strip():
        return short_name
    product = application.product
    if isinstance(product, str) and product.strip():
        return product
    raise DockerfileError("application product metadata must be a nonempty string")


def _optional_string(mapping: Mapping[str, Any], key: str, *, owner: str) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise DockerfileError(f"{owner} {key} must be a string")
    value = value.strip()
    return value or None


def _resolve_path(value: str, *, topology_dir: Path, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = topology_dir / path
    resolved = path.resolve()
    if not resolved.exists():
        raise DockerfileError(f"{label} does not exist: {resolved}")
    return resolved


def _extra_args(value: str, *, node_name: str) -> tuple[str, ...]:
    try:
        args = tuple(shlex.split(value))
    except ValueError as error:
        raise DockerfileError(f"node {node_name} has invalid Docker arguments: {error}") from error
    for argument in args:
        if argument in _RESERVED_ARGUMENTS or argument.startswith(("--file=", "--tag=")):
            raise DockerfileError(
                f"node {node_name} must not set {argument} in Docker arguments; "
                "the plugin owns the Dockerfile and image tag"
            )
        if argument.startswith("-f") and argument != "--file":
            raise DockerfileError(f"node {node_name} must not set {argument} in Docker arguments")
        if argument.startswith("-t") and argument != "--tag":
            raise DockerfileError(f"node {node_name} must not set {argument} in Docker arguments")
    return args


def build_requests_from_topology(
    topology_path: Path,
    topology_data: dict[str, Any],
    *,
    application_name: str,
) -> list[BuildRequest]:
    prefix = environment_prefix(application_name)
    dockerfile_key = f"{prefix}_DOCKERFILE"
    context_key = f"{prefix}_DOCKER_CTX"
    args_key = f"{prefix}_DOCKER_ARGS"
    variable_prefix = f"{prefix}_DOCKER_VAR_"
    topology_dir = topology_path.resolve().parent
    requests: list[BuildRequest] = []

    for node in topology_nodes(topology_data):
        environment = node.data.get("env")
        if environment is None:
            continue
        if not isinstance(environment, dict):
            raise DockerfileError(f"node {node.name} env must be a YAML mapping")
        dockerfile_value = _optional_string(environment, dockerfile_key, owner=f"node {node.name}")
        if dockerfile_value is None:
            continue
        context_value = _optional_string(environment, context_key, owner=f"node {node.name}")
        if context_value is None:
            raise DockerfileError(f"node {node.name} sets {dockerfile_key} but not {context_key}")
        image = _optional_string(node.data, "image", owner=f"node {node.name}")
        if image is None:
            raise DockerfileError(f"node {node.name} sets {dockerfile_key} but has no image tag")
        dockerfile = _resolve_path(dockerfile_value, topology_dir=topology_dir, label=dockerfile_key)
        if not dockerfile.is_file():
            raise DockerfileError(f"{dockerfile_key} must name a file: {dockerfile}")
        context = _resolve_path(context_value, topology_dir=topology_dir, label=context_key)
        if not context.is_dir():
            raise DockerfileError(f"{context_key} must name a directory: {context}")
        build_args: list[tuple[str, str]] = []
        for key, value in environment.items():
            if not isinstance(key, str) or not key.startswith(variable_prefix):
                continue
            name = key.removeprefix(variable_prefix)
            if not name:
                raise DockerfileError(f"node {node.name} has an empty Docker build-argument name")
            if not isinstance(value, str):
                raise DockerfileError(f"node {node.name} {key} must be a string")
            build_args.append((name, value))
        extra_value = _optional_string(environment, args_key, owner=f"node {node.name}")
        requests.append(
            BuildRequest(
                node_name=node.name,
                image=image,
                dockerfile=dockerfile,
                context=context,
                build_args=tuple(sorted(build_args)),
                extra_args=() if extra_value is None else _extra_args(extra_value, node_name=node.name),
            )
        )
    return requests
