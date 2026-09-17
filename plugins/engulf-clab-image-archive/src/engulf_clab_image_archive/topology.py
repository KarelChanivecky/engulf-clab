from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from engulf_clab_lab_parser import EffectiveNode, effective_nodes
from engulf_clab_lab_parser.session import (
    TopologyError,
)
from engulf_clab_lab_parser.session import (
    load_topology as load_parsed_topology,
)
from engulf_clab_lab_parser.session import (
    topology_path_from_args as parsed_topology_path_from_args,
)

from .errors import ImageArchiveError


def topology_path_from_args(args: tuple[str, ...], cwd: Path | None = None) -> Path:
    try:
        return parsed_topology_path_from_args(args, cwd)
    except TopologyError as error:
        raise ImageArchiveError(str(error)) from error


def load_topology(path: Path, environment: Mapping[str, str] | None = None) -> dict[str, Any]:
    try:
        return load_parsed_topology(path, environment)
    except TopologyError as error:
        raise ImageArchiveError(str(error)) from error


def topology_nodes(topology_data: dict[str, Any]) -> list[EffectiveNode]:
    topology = topology_data.get("topology")
    if not isinstance(topology, dict):
        raise ImageArchiveError("topology file is missing topology mapping")
    nodes = topology.get("nodes")
    if not isinstance(nodes, dict):
        raise ImageArchiveError("topology file is missing topology.nodes mapping")
    try:
        return list(effective_nodes(topology_data))
    except TopologyError as error:
        raise ImageArchiveError(str(error)) from error
