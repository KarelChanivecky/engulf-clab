from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engulf_clab_ensure_vrnetlab import vrnetlab_type_env
from engulf_clab_lab_parser import TopologyError, effective_nodes
from engulf_clab_vrnetlab_build_api import VrnetlabBuildAPI

from .errors import VrnetlabError

_IMAGE_EXPRESSION = re.compile(r"^\$\{([^}:]+)(?:(:?[-=])(.*))?\}$")


@dataclass(frozen=True)
class BuildRequest:
    node_name: str
    image: str
    builder_type: str
    source: Path | None


def resolve_image_expression(value: str, environ: Mapping[str, str]) -> str:
    match = _IMAGE_EXPRESSION.match(value)
    if match is None:
        if value.startswith("${") or "${" in value:
            raise VrnetlabError(f"unsupported image expression: {value}")
        return value

    name, operator, default = match.groups()
    env_value = environ.get(name)
    if operator is None:
        if env_value is None:
            raise VrnetlabError(
                f"environment variable {name} is required by image expression {value}"
            )
        return env_value
    if operator in (":=", ":-"):
        return env_value if env_value else (default or "")
    raise VrnetlabError(f"unsupported image expression operator {operator} in {value}")


def build_requests_from_topology(
    topology_data: dict[str, Any],
    environ: Mapping[str, str],
    build_api: VrnetlabBuildAPI | None,
) -> tuple[BuildRequest, ...]:
    topology = topology_data.get("topology")
    if not isinstance(topology, dict) or not isinstance(topology.get("nodes"), dict):
        raise VrnetlabError("topology file is missing topology.nodes mapping")
    try:
        nodes = effective_nodes(topology_data)
    except TopologyError as error:
        raise VrnetlabError(str(error)) from error

    requests: list[BuildRequest] = []
    type_environment = vrnetlab_type_env()
    for node in nodes:
        node_environment = node.data.get("env", {})
        if not isinstance(node_environment, Mapping):
            raise VrnetlabError(f"node {node.name} env must be a YAML mapping")
        builder_type = node_environment.get(type_environment)
        if not isinstance(builder_type, str) or not builder_type.strip():
            continue
        image_value = node.data.get("image")
        if not isinstance(image_value, str) or not image_value.strip():
            raise VrnetlabError(f"vrnetlab node {node.name} is missing image")
        image = resolve_image_expression(image_value.strip(), environ)
        if not image:
            raise VrnetlabError(f"vrnetlab node {node.name} resolved to an empty image")
        requests.append(
            BuildRequest(
                node_name=node.name,
                image=image,
                builder_type=builder_type.strip(),
                source=None if build_api is None else build_api.source_for(node.name),
            )
        )

    if build_api is not None:
        default_type_nodes: dict[str, list[str]] = {}
        for request in requests:
            if build_api.uses_default_source(request.node_name):
                default_type_nodes.setdefault(request.builder_type, []).append(
                    request.node_name
                )
        if len(default_type_nodes) > 1:
            details = "; ".join(
                f"{builder_type}: {', '.join(node_names)}"
                for builder_type, node_names in default_type_nodes.items()
            )
            raise VrnetlabError(
                "nodes using the default vrnetlab image source must all use the same "
                f"ECLAB_VRNETLAB_TYPE; found {details}"
            )

    return tuple(requests)
