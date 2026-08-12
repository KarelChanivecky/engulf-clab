from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .errors import DockerfileError

TOPOLOGY_PATTERNS = ("*.clab.yml", "*.clab.yaml", "clab.yml", "clab.yaml", "topology.yml", "topology.yaml")
TOPOLOGY_OPTIONS = frozenset(("-t", "--topo", "--topology"))


@dataclass(frozen=True)
class TopologyNode:
    name: str
    data: dict[str, Any]


def topology_path_from_args(args: tuple[str, ...], cwd: Path | None = None) -> Path:
    for index, argument in enumerate(args):
        if argument in TOPOLOGY_OPTIONS:
            if index + 1 >= len(args):
                raise DockerfileError(f"{argument} requires a topology path")
            return Path(args[index + 1]).expanduser()
        for option in TOPOLOGY_OPTIONS:
            prefix = f"{option}="
            if argument.startswith(prefix):
                value = argument[len(prefix) :]
                if not value:
                    raise DockerfileError(f"{option} requires a topology path")
                return Path(value).expanduser()

    search_dir = cwd or Path.cwd()
    matches = [
        candidate
        for pattern in TOPOLOGY_PATTERNS
        for candidate in sorted(search_dir.glob(pattern))
        if candidate.is_file()
    ]
    unique = list(dict.fromkeys(path.resolve() for path in matches))
    if not unique:
        raise DockerfileError(f"could not find a Containerlab topology in {search_dir}")
    if len(unique) > 1:
        formatted = "\n".join(f"  {path}" for path in unique)
        raise DockerfileError("multiple Containerlab topology files found; pass one explicitly:\n" + formatted)
    return unique[0]


def load_topology(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise DockerfileError(f"topology file does not exist: {path}")
    try:
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except (UnicodeError, yaml.YAMLError) as error:
        raise DockerfileError(f"could not parse topology file {path}: {error}") from error
    if not isinstance(data, dict):
        raise DockerfileError("topology file must contain a YAML mapping")
    return data


def topology_nodes(topology_data: dict[str, Any]) -> list[TopologyNode]:
    topology = topology_data.get("topology")
    if not isinstance(topology, dict):
        raise DockerfileError("topology file is missing topology mapping")
    nodes = topology.get("nodes")
    if not isinstance(nodes, dict):
        raise DockerfileError("topology file is missing topology.nodes mapping")
    return [TopologyNode(str(name), data) for name, data in nodes.items() if isinstance(data, dict)]
