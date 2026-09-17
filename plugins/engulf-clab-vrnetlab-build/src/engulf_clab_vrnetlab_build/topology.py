from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engulf_clab_lab_parser import TopologyError, effective_nodes
from engulf_clab_lab_parser.session import (
    load_topology as load_parsed_topology,
)
from engulf_clab_lab_parser.session import (
    topology_path_from_args as parsed_topology_path_from_args,
)

from .errors import VrnetlabError


@dataclass(frozen=True)
class TopologyNode:
    name: str
    data: Mapping[str, Any]


def load_topology(
    path: Path, environment: Mapping[str, str] | None = None
) -> dict[str, Any]:
    try:
        return load_parsed_topology(path, environment)
    except TopologyError as error:
        raise VrnetlabError(str(error)) from error


def topology_name(topology_data: dict[str, Any]) -> str:
    name = topology_data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise VrnetlabError("topology file is missing a non-empty name")
    return name.strip()


def topology_nodes(topology_data: dict[str, Any]) -> list[TopologyNode]:
    topology = topology_data.get("topology")
    if not isinstance(topology, dict):
        raise VrnetlabError("topology file is missing topology mapping")

    nodes = topology.get("nodes")
    if not isinstance(nodes, dict):
        raise VrnetlabError("topology file is missing topology.nodes mapping")

    try:
        resolved = effective_nodes(topology_data)
    except TopologyError as error:
        raise VrnetlabError(str(error)) from error
    return [TopologyNode(name=node.name, data=node.data) for node in resolved]


def topology_path_from_args(args: tuple[str, ...], cwd: Path | None = None) -> Path:
    try:
        return parsed_topology_path_from_args(args, cwd)
    except TopologyError as error:
        raise VrnetlabError(str(error)) from error
