from __future__ import annotations

import copy
import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml  # type: ignore[import-untyped]
from engulf_api import InvocationAPI

from .environment import (
    EnvFileError,
    EnvironmentExpansionError,
    expand_environment,
    topology_environment,
)

TOPOLOGY_CONTEXT = "engulf_clab.topology.session"
PathPart = str | int
YamlPath = tuple[PathPart, ...]
_OPTIONS = frozenset(("-t", "--topo", "--topology"))
_PATTERNS = ("*.clab.yml", "*.clab.yaml", "clab.yml", "clab.yaml", "topology.yml", "topology.yaml")
# Temp topology files written beside the source by the lab writer plugin
# (engulf_clab.lab_writer). The parser must ignore these when globbing for the
# active topology: they are byproducts of a deploy, never a lab author's input.
# Kept here as the single source of truth so the writer imports it rather than
# duplicating the prefix and risking drift.
WRITER_TEMP_PREFIX = ".engulf-clab-lab-"


def is_topology_mutation_command(args: tuple[str, ...]) -> bool:
    """Return whether one call has a single source topology to mutate."""
    if not args:
        return False
    if args[0] == "deploy":
        return True
    if args[0] != "redeploy":
        return False
    rest = args[1:]
    if any(value in {"-a", "--all"} for value in rest):
        return False
    has_topology = any(
        value in _OPTIONS
        or any(value.startswith(option + "=") for option in _OPTIONS)
        for value in rest
    )
    has_name = any(
        value == "--name" or value.startswith("--name=") for value in rest
    )
    return has_topology or not has_name


def derived_topology_path(source: Path) -> Path:
    """Return the stable writer path associated with one source topology."""
    identity = hashlib.sha256(str(source.resolve()).encode("utf-8")).hexdigest()[:16]
    return source.resolve().parent / f"{WRITER_TEMP_PREFIX}{identity}.clab.yml"

class TopologyError(RuntimeError): pass

def topology_path_from_args(args: tuple[str, ...], cwd: Path | None = None) -> Path:
    found: list[Path] = []
    for index, argument in enumerate(args):
        if argument in _OPTIONS:
            if index + 1 >= len(args): raise TopologyError(f"{argument} requires a topology path")
            found.append(Path(args[index + 1]).expanduser())
        else:
            for option in _OPTIONS:
                if argument.startswith(option + "="):
                    value = argument.removeprefix(option + "=")
                    if not value: raise TopologyError(f"{option} requires a topology path")
                    found.append(Path(value).expanduser())
    if len(found) > 1: raise TopologyError("multiple topology options are not supported")
    if found: return found[0].resolve()
    root = cwd or Path.cwd(); matches = list(dict.fromkeys(p.resolve() for pattern in _PATTERNS for p in sorted(root.glob(pattern)) if p.is_file() and not p.name.startswith(WRITER_TEMP_PREFIX)))
    if len(matches) != 1: raise TopologyError("pass exactly one topology with -t, --topo, or --topology")
    return matches[0]

def load_topology(
    path: Path, environment: Mapping[str, str] | None = None
) -> dict[str, Any]:
    if not path.is_file(): raise TopologyError(f"topology file does not exist: {path}")
    try:
        source = path.read_text(encoding="utf-8")
        # Resolved here rather than by each caller: every plugin reaches a
        # topology through this function, and deriving the environment anywhere
        # else would let them expand the same document differently.
        effective = topology_environment(path, os.environ if environment is None else environment)
        rendered = expand_environment(source, effective)
        data = yaml.safe_load(rendered)
    except (OSError, EnvFileError, EnvironmentExpansionError, yaml.YAMLError) as error: raise TopologyError(f"could not parse topology {path}: {error}") from error
    if not isinstance(data, dict): raise TopologyError("topology file must contain a YAML mapping")
    return data

def _freeze(value: Any) -> Any:
    if isinstance(value, dict): return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list): return tuple(_freeze(item) for item in value)
    return value

@dataclass(frozen=True)
class _Operation:
    owner: str; kind: str; path: YamlPath; value: Any = None

class TopologyEditor:
    def __init__(self, session: TopologySession, owner: str) -> None: self._session, self._owner = session, owner
    def delete(self, path: YamlPath) -> None: self._session._record(self._owner, "delete", path)
    def modify(self, path: YamlPath, value: Any) -> None: self._session._record(self._owner, "modify", path, value)
    def add(self, path: YamlPath, value: Any) -> None: self._session._record(self._owner, "add", path, value)

class TopologySession:
    def __init__(self, path: Path, original: dict[str, Any]) -> None:
        self.path, self.original, self._data = path, _freeze(original), original
        self._operations: list[_Operation] = []
    def editor(self, owner: str) -> TopologyEditor: return TopologyEditor(self, owner)
    def original_document(self) -> dict[str, Any]: return copy.deepcopy(self._data)
    def _record(self, owner: str, kind: str, path: YamlPath, value: Any = None) -> None:
        if not owner or not isinstance(path, tuple) or not path: raise TopologyError("owner and nonempty tuple path are required")
        if any(not isinstance(part, (str, int)) for part in path): raise TopologyError("YAML paths contain only string keys and integer indexes")
        self._operations.append(_Operation(owner, kind, path, copy.deepcopy(value)))
    def materialize(self) -> dict[str, Any]:
        data = copy.deepcopy(self._data); deletes = [op.path for op in self._operations if op.kind == "delete"]
        def deleted(path: YamlPath) -> bool: return any(path[:len(item)] == item for item in deletes)
        for path in sorted(set(deletes), key=len, reverse=True): _delete(data, path)
        active = [op for op in self._operations if op.kind != "delete" and not deleted(op.path)]
        seen: dict[YamlPath, _Operation] = {}
        for op in active:
            key = op.path
            if key in seen and (seen[key].kind != op.kind or seen[key].value != op.value): raise TopologyError(f"conflicting operations at {op.path} from {seen[key].owner} and {op.owner}")
            seen[key] = op
        for kind in ("modify", "add"):
            for op in sorted((op for op in active if op.kind == kind), key=lambda item: len(item.path)):
                if kind == "modify": _modify(data, op.path, op.value)
                else: _add(data, op.path, op.value)
        return data

def _parent(root: Any, path: YamlPath, create: bool) -> tuple[Any, PathPart]:
    node = root
    for part in path[:-1]:
        if isinstance(node, dict):
            if part not in node:
                if not create: raise TopologyError(f"missing YAML path {path}")
                node[part] = {}
            node = node[part]
        elif isinstance(node, list) and isinstance(part, int) and 0 <= part < len(node): node = node[part]
        else: raise TopologyError(f"invalid YAML path {path}")
    return node, path[-1]
def _delete(root: Any, path: YamlPath) -> None:
    try: parent, key = _parent(root, path, False)
    except TopologyError: return
    if isinstance(parent, dict): parent.pop(key, None)
    elif isinstance(parent, list) and isinstance(key, int) and 0 <= key < len(parent): del parent[key]
def _modify(root: Any, path: YamlPath, value: Any) -> None:
    parent, key = _parent(root, path, True)
    if isinstance(parent, dict):
        parent[key] = value
        return
    if isinstance(parent, list) and isinstance(key, int) and 0 <= key < len(parent):
        parent[key] = value
        return
    raise TopologyError(f"invalid YAML modification path {path}")
def _add(root: Any, path: YamlPath, value: Any) -> None:
    parent, key = _parent(root, path, True)
    if isinstance(parent, dict):
        if key in parent: raise TopologyError(f"YAML addition already exists at {path}")
        parent[key] = value
    elif isinstance(parent, list) and isinstance(key, int) and 0 <= key <= len(parent): parent.insert(key, value)
    else: raise TopologyError(f"invalid YAML addition path {path}")
def editor(api: InvocationAPI, owner: str) -> TopologyEditor:
    value = api.require_context(TOPOLOGY_CONTEXT)
    if not isinstance(value, TopologySession): raise TopologyError("invalid topology mutation context")
    return value.editor(owner)
