"""Configured-root topology discovery and safe lab identity resolution."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

import yaml

from .config import LabRoot, ServiceConfig
from .errors import NotFoundError, OperationError, RequestError

_TOPOLOGY_BASENAMES = frozenset({"clab.yml", "clab.yaml", "topology.yml", "topology.yaml"})
_SKIPPED_DIRECTORIES = frozenset({".git", ".engulf-clab", ".venv", "__pycache__", "build", "dist"})
_MAX_TOPOLOGY_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class Lab:
    """A topology selected through one configured root."""

    identifier: str
    root: LabRoot
    relative_path: PurePosixPath
    path: Path
    display_name: str | None
    parse_error: str | None

    def public(self) -> dict[str, object]:
        """Return discovery metadata that does not expose arbitrary host paths."""
        result: dict[str, object] = {
            "id": self.identifier,
            "root": self.root.identifier,
            "topology": self.relative_path.as_posix(),
            "name": self.display_name,
        }
        if self.parse_error is not None:
            result["error"] = self.parse_error
        return result


class LabCatalog:
    """Discovers only topology files safely rooted in administrator configuration."""

    def __init__(self, config: ServiceConfig) -> None:
        self._config = config

    def list_labs(self) -> list[Lab]:
        """Discover supported topology files under all configured roots."""
        labs: list[Lab] = []
        for root in self._config.lab_roots.values():
            labs.extend(self._discover_root(root))
        return sorted(labs, key=lambda item: item.identifier)

    def resolve(self, identifier: object) -> Lab:
        """Resolve only an ID currently present in discovery output."""
        if not isinstance(identifier, str) or not identifier:
            raise RequestError("lab_id must be a nonempty discovered lab ID")
        for lab in self.list_labs():
            if lab.identifier == identifier:
                return lab
        raise NotFoundError("lab ID is not present under a configured lab root")

    def load_document(self, lab: Lab) -> dict[str, Any]:
        """Load a bounded YAML mapping for one already-resolved lab."""
        return _load_topology(lab.path)

    def _discover_root(self, root: LabRoot) -> list[Lab]:
        result: list[Lab] = []
        for base, directories, files in os.walk(root.path, followlinks=False):
            directories[:] = [
                name
                for name in directories
                if name not in _SKIPPED_DIRECTORIES and not (Path(base) / name).is_symlink()
            ]
            for filename in files:
                candidate = Path(base) / filename
                if not _is_topology_filename(candidate.name):
                    continue
                try:
                    resolved = candidate.resolve(strict=True)
                    if not resolved.is_file() or not resolved.is_relative_to(root.path):
                        continue
                    relative = PurePosixPath(candidate.relative_to(root.path).as_posix())
                except (OSError, ValueError):
                    continue
                # IDs are audit-log-safe even when a filesystem path contains
                # whitespace or control characters. Resolution always compares
                # against fresh discovery rather than decoding caller input.
                identifier = f"{root.identifier}:{quote(relative.as_posix(), safe='/._-')}"
                display_name, parse_error = _discovery_metadata(resolved)
                result.append(
                    Lab(
                        identifier=identifier,
                        root=root,
                        relative_path=relative,
                        path=resolved,
                        display_name=display_name,
                        parse_error=parse_error,
                    )
                )
        return result


def topology_name(document: Mapping[str, Any], path: Path) -> str:
    """Use Containerlab's topology name convention without exposing raw YAML."""
    value = document.get("name")
    if isinstance(value, str) and value.strip():
        return value.strip()
    name = path.name
    for suffix in (".clab.yml", ".clab.yaml", ".yml", ".yaml"):
        if name.endswith(suffix):
            return name.removesuffix(suffix)
    return path.stem


def topology_nodes(document: Mapping[str, Any]) -> tuple[str, ...]:
    """Return valid node names or a safe topology validation failure."""
    topology = document.get("topology")
    nodes = topology.get("nodes") if isinstance(topology, Mapping) else None
    if not isinstance(nodes, Mapping):
        raise OperationError("topology.nodes must be a mapping")
    names = tuple(name for name in nodes if isinstance(name, str) and name)
    if len(names) != len(nodes):
        raise OperationError("topology node names must be nonempty strings")
    return names


def _is_topology_filename(name: str) -> bool:
    return name in _TOPOLOGY_BASENAMES or name.endswith((".clab.yml", ".clab.yaml"))


def _discovery_metadata(path: Path) -> tuple[str | None, str | None]:
    try:
        document = _load_topology(path)
    except OperationError:
        return None, "topology YAML is invalid"
    name = document.get("name")
    return (name.strip(), None) if isinstance(name, str) and name.strip() else (None, None)


def _load_topology(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > _MAX_TOPOLOGY_BYTES:
            raise OperationError("topology exceeds the maximum supported size")
        with path.open(encoding="utf-8") as handle:
            value = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as error:
        raise OperationError("topology YAML cannot be read or parsed") from error
    if not isinstance(value, dict):
        raise OperationError("topology must contain a YAML mapping")
    return value
