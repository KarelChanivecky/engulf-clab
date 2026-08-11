from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .contract import (
    DEFAULT_APPLICATION_NAME,
    LEGACY_VRNETLAB_TYPE_ENV,
    vrnetlab_type_env,
)
from .errors import EnsureVrnetlabError

TOPOLOGY_PATTERNS = (
    "*.clab.yml",
    "*.clab.yaml",
    "clab.yml",
    "clab.yaml",
    "topology.yml",
    "topology.yaml",
)
TOPOLOGY_OPTIONS = frozenset(("-t", "--topo", "--topology"))


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
        raise EnsureVrnetlabError(f"could not find a Containerlab topology in {search_dir}")
    if len(matches) > 1:
        formatted = "\n".join(f"  {match}" for match in matches)
        raise EnsureVrnetlabError(
            "multiple Containerlab topology files found; pass one explicitly:\n" + formatted
        )
    return matches[0]


def topology_path_from_args(args: tuple[str, ...], cwd: Path | None = None) -> Path:
    for index, argument in enumerate(args):
        if argument in TOPOLOGY_OPTIONS:
            if index + 1 >= len(args):
                raise EnsureVrnetlabError(f"{argument} requires a topology path")
            return Path(args[index + 1]).expanduser()

        for option in TOPOLOGY_OPTIONS:
            prefix = f"{option}="
            if argument.startswith(prefix):
                value = argument[len(prefix) :]
                if not value:
                    raise EnsureVrnetlabError(f"{option} requires a topology path")
                return Path(value).expanduser()

    return find_default_topology(cwd)


def load_topology(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise EnsureVrnetlabError(f"topology file does not exist: {path}")

    try:
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except (UnicodeError, yaml.YAMLError) as error:
        raise EnsureVrnetlabError(f"could not parse topology file {path}: {error}") from error
    if not isinstance(data, dict):
        raise EnsureVrnetlabError(f"topology file must contain a YAML mapping: {path}")
    return data


def topology_needs_vrnetlab(
    topology_data: dict[str, Any],
    *,
    application_name: str = DEFAULT_APPLICATION_NAME,
) -> bool:
    topology = topology_data.get("topology")
    if not isinstance(topology, dict):
        return False
    nodes = topology.get("nodes")
    if not isinstance(nodes, dict):
        return False

    type_environments = [vrnetlab_type_env(application_name)]
    if application_name == DEFAULT_APPLICATION_NAME:
        type_environments.append(LEGACY_VRNETLAB_TYPE_ENV)
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
