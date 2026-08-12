from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .errors import VrnetlabError

TOPOLOGY_PATTERNS = (
    "*.clab.yml",
    "*.clab.yaml",
    "clab.yml",
    "clab.yaml",
    "topology.yml",
    "topology.yaml",
)

TOPOLOGY_OPTIONS = frozenset(("-t", "--topo", "--topology"))


@dataclass(frozen=True)
class TopologyNode:
    name: str
    data: dict[str, Any]


def find_default_topology(cwd: Path | None = None) -> Path:
    search_dir = cwd or Path.cwd()
    matches: list[Path] = []
    seen: set[Path] = set()

    for pattern in TOPOLOGY_PATTERNS:
        for candidate in sorted(search_dir.glob(pattern)):
            resolved = candidate.resolve()
            if candidate.is_file() and resolved not in seen:
                matches.append(candidate)
                seen.add(resolved)

    if not matches:
        raise VrnetlabError(f"could not find a Containerlab topology in {search_dir}")
    if len(matches) > 1:
        formatted = "\n".join(f"  {match}" for match in matches)
        raise VrnetlabError(
            "multiple Containerlab topology files found; pass one explicitly:\n" + formatted
        )
    return matches[0]


def load_topology(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise VrnetlabError(f"topology file does not exist: {path}")

    try:
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except (UnicodeError, yaml.YAMLError) as error:
        raise VrnetlabError(f"could not parse topology file {path}: {error}") from error

    if not isinstance(data, dict):
        raise VrnetlabError(f"topology file must contain a YAML mapping: {path}")
    return data


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

    parsed: list[TopologyNode] = []
    for name, node_data in nodes.items():
        if isinstance(node_data, dict):
            parsed.append(TopologyNode(name=str(name), data=node_data))
    return parsed


def topology_path_from_args(args: tuple[str, ...], cwd: Path | None = None) -> Path:
    for index, argument in enumerate(args):
        if argument in TOPOLOGY_OPTIONS:
            if index + 1 >= len(args):
                raise VrnetlabError(f"{argument} requires a topology path")
            return Path(args[index + 1]).expanduser()

        for option in TOPOLOGY_OPTIONS:
            prefix = f"{option}="
            if argument.startswith(prefix):
                value = argument[len(prefix) :]
                if not value:
                    raise VrnetlabError(f"{option} requires a topology path")
                return Path(value).expanduser()

    return find_default_topology(cwd)
