from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .errors import WanError

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
        raise WanError(f"could not find a Containerlab topology in {search_dir}")
    if len(matches) > 1:
        formatted = "\n".join(f"  {match}" for match in matches)
        raise WanError(
            "multiple Containerlab topology files found; pass one explicitly:\n"
            + formatted
        )
    return matches[0]


def load_topology(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise WanError(f"topology file does not exist: {path}")

    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if not isinstance(data, dict):
        raise WanError(f"topology file must contain a YAML mapping: {path}")
    return data


def topology_path_from_args(args: tuple[str, ...], cwd: Path | None = None) -> Path:
    for index, argument in enumerate(args):
        if argument in TOPOLOGY_OPTIONS:
            if index + 1 >= len(args):
                raise WanError(f"{argument} requires a topology path")
            return Path(args[index + 1]).expanduser()

        for option in TOPOLOGY_OPTIONS:
            prefix = f"{option}="
            if argument.startswith(prefix):
                value = argument[len(prefix) :]
                if not value:
                    raise WanError(f"{option} requires a topology path")
                return Path(value).expanduser()

    return find_default_topology(cwd)
