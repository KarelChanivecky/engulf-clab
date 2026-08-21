from __future__ import annotations

from pathlib import Path
from typing import Any

from engulf_clab_lab_parser.session import (
    TopologyError,
)
from engulf_clab_lab_parser.session import (
    load_topology as load_parsed_topology,
)
from engulf_clab_lab_parser.session import (
    topology_path_from_args as parsed_topology_path_from_args,
)

from .contract import LEGACY_VRNETLAB_TYPE_ENV, vrnetlab_type_env
from .errors import EnsureVrnetlabError


def topology_path_from_args(args: tuple[str, ...], cwd: Path | None = None) -> Path:
    try:
        return parsed_topology_path_from_args(args, cwd)
    except TopologyError as error:
        raise EnsureVrnetlabError(str(error)) from error


def load_topology(path: Path) -> dict[str, Any]:
    try:
        return load_parsed_topology(path)
    except TopologyError as error:
        raise EnsureVrnetlabError(str(error)) from error


def topology_needs_vrnetlab(topology_data: dict[str, Any]) -> bool:
    topology = topology_data.get("topology")
    if not isinstance(topology, dict):
        return False
    nodes = topology.get("nodes")
    if not isinstance(nodes, dict):
        return False

    type_environments = {vrnetlab_type_env(), LEGACY_VRNETLAB_TYPE_ENV}
    for node_data in nodes.values():
        if not isinstance(node_data, dict):
            continue
        node_environment = node_data.get("env")
        if not isinstance(node_environment, dict):
            continue
        for type_environment in type_environments:
            builder_type = node_environment.get(type_environment)
            if isinstance(builder_type, str) and builder_type.strip():
                return True
    return False
