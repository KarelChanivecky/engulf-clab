from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
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

from .errors import DockerfileError


@dataclass(frozen=True)
class TopologyNode:
    name: str
    data: dict[str, Any]


def topology_path_from_args(args: tuple[str, ...], cwd: Path | None = None) -> Path:
    try:
        return parsed_topology_path_from_args(args, cwd)
    except TopologyError as error:
        raise DockerfileError(str(error)) from error


def load_topology(
    path: Path, environment: Mapping[str, str] | None = None
) -> dict[str, Any]:
    try:
        return load_parsed_topology(path, environment)
    except TopologyError as error:
        raise DockerfileError(str(error)) from error


def topology_nodes(topology_data: dict[str, Any]) -> list[TopologyNode]:
    topology = topology_data.get("topology")
    if not isinstance(topology, dict):
        raise DockerfileError("topology file is missing topology mapping")
    nodes = topology.get("nodes")
    if not isinstance(nodes, dict):
        raise DockerfileError("topology file is missing topology.nodes mapping")
    return [TopologyNode(str(name), data) for name, data in nodes.items() if isinstance(data, dict)]
