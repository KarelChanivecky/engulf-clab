"""Immutable, provenance-bearing views of Containerlab node declarations.

This resolves topology inheritance, not kind-specific runtime defaults, env-file
contents, or native dispatcher's derived paths and lifecycle configuration.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

from .session import TopologyError, YamlPath

Level = Literal["defaults", "kind", "group", "node"]
_SECTIONS: tuple[tuple[str, Level], ...] = (
    ("kinds", "kind"),
    ("groups", "group"),
    ("nodes", "node"),
)
_STRING_MAPS = frozenset({"env", "labels", "sysctls", "tmpfs"})
_MERGED_LISTS = frozenset(
    {
        "env-files",
        "devices",
        "cap-add",
        "security-opts",
        "exec",
        "binds",
        "volumes",
    }
)
_NODE_ONLY = frozenset({"mgmt-ipv4", "mgmt-ipv6", "aliases"})
_NUMBERS = frozenset({"cpu", "startup-delay"})
_STRING_FIELDS = frozenset(
    {
        "kind",
        "group",
        "type",
        "image",
        "network-mode",
        "license",
        "startup-config",
        "image-pull-policy",
        "position",
        "hostname",
        "entrypoint",
        "cmd",
        "restart-policy",
        "cgroupns-mode",
        "cgroup-parent",
        "pid-mode",
        "shm-size",
        "user",
        "runtime",
        "cpu-set",
        "memory",
        "link-apply-mode",
    }
)


def _immutable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _immutable(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_immutable(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class FieldOrigin:
    level: Level
    name: str | None
    path: YamlPath


@dataclass(frozen=True, slots=True)
class TopologyDeclaration:
    origin: FieldOrigin
    data: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", _immutable(self.data))

    def field_origin(self, *field: str | int) -> FieldOrigin:
        return FieldOrigin(
            self.origin.level, self.origin.name, self.origin.path + field
        )


@dataclass(frozen=True, slots=True)
class EffectiveNode:
    name: str
    data: Mapping[str, Any]
    origins: Mapping[YamlPath, FieldOrigin]
    declarations: Mapping[YamlPath, tuple[FieldOrigin, ...]]

    def __post_init__(self) -> None:
        for field in ("data", "origins", "declarations"):
            object.__setattr__(self, field, _immutable(getattr(self, field)))

    def origin(self, *field: str | int) -> FieldOrigin | None:
        """Return the winning declaration, or None for an absent field."""
        return self.origins.get(field)

    def declared_origins(self, *field: str | int) -> tuple[FieldOrigin, ...]:
        """Include shadowed declarations, in defaults-to-node order."""
        return self.declarations.get(field, ())


def _mapping(value: Any, owner: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TopologyError(f"{owner} must be a mapping")
    return value


def topology_declarations(
    document: Mapping[str, Any],
) -> tuple[TopologyDeclaration, ...]:
    """Enumerate every declaration, including unused kinds/groups, for redaction.

    Malformed definitions remain Containerlab's validation responsibility here;
    effective_nodes validates definitions actually selected by a node.
    """
    topology = document.get("topology")
    if not isinstance(topology, Mapping):
        return ()
    declarations: list[TopologyDeclaration] = []
    defaults = topology.get("defaults")
    if isinstance(defaults, Mapping):
        declarations.append(
            TopologyDeclaration(
                FieldOrigin("defaults", None, ("topology", "defaults")), defaults
            )
        )
    for section, level in _SECTIONS:
        definitions = topology.get(section)
        if not isinstance(definitions, Mapping):
            continue
        for name, data in definitions.items():
            if isinstance(data, Mapping):
                declarations.append(
                    TopologyDeclaration(
                        FieldOrigin(level, str(name), ("topology", section, name)), data
                    )
                )
    return tuple(declarations)


def _selector(value: Any, path: YamlPath) -> str | None:
    if isinstance(value, bool):
        value = "true" if value else "false"
    elif isinstance(value, (int, float)):
        value = str(value)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise TopologyError(f"{'.'.join(map(str, path))} must be a string")
    return value


def _field_origins(
    declaration: TopologyDeclaration, path: YamlPath, value: Any
) -> Iterator[tuple[YamlPath, FieldOrigin]]:
    yield path, declaration.field_origin(*path)
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield from _field_origins(declaration, path + (key,), item)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _field_origins(declaration, path + (index,), item)


def _definition(
    section: Mapping[str, Any], level: Level, name: str | None
) -> TopologyDeclaration:
    plural = "kinds" if level == "kind" else "groups"
    path = ("topology", plural, name or "")
    return TopologyDeclaration(
        FieldOrigin(level, name, path),
        _mapping(section.get(name or ""), ".".join(path)),
    )


def _kind_sources(
    node: TopologyDeclaration, default: TopologyDeclaration, groups: Mapping[str, Any]
) -> Iterator[TopologyDeclaration]:
    yield node
    for source in (node, default):
        group_name = _selector(
            source.data.get("group"), source.origin.path + ("group",)
        )
        if group_name is not None:
            yield _definition(groups, "group", group_name)
    yield default


def effective_nodes(document: Mapping[str, Any]) -> tuple[EffectiveNode, ...]:
    """Resolve defaults < kind < group < node without changing the document."""
    topology = _mapping(document.get("topology"), "topology")
    nodes = _mapping(topology.get("nodes"), "topology.nodes")
    defaults = _mapping(topology.get("defaults"), "topology.defaults")
    kinds = _mapping(topology.get("kinds"), "topology.kinds")
    groups = _mapping(topology.get("groups"), "topology.groups")
    default = TopologyDeclaration(
        FieldOrigin("defaults", None, ("topology", "defaults")), defaults
    )
    result: list[EffectiveNode] = []

    for name, raw_node in nodes.items():
        if not isinstance(name, str):
            raise TopologyError("topology nodes must have string names")
        node = TopologyDeclaration(
            FieldOrigin("node", name, ("topology", "nodes", name)),
            _mapping(raw_node, f"topology node {name!r}"),
        )
        # Kind selection deliberately does not recurse through a kind's group:
        # this is the same finite selection chain as Go's GetNodeKind.
        kind_name: str | None = None
        kind_origin: FieldOrigin | None = None
        for declaration in _kind_sources(node, default, groups):
            kind_name = _selector(
                declaration.data.get("kind"), declaration.origin.path + ("kind",)
            )
            if kind_name is not None:
                kind_origin = declaration.field_origin("kind")
                break
        kind = _definition(kinds, "kind", kind_name)
        group_name: str | None = None
        group_origin: FieldOrigin | None = None
        group_sources = (default,) if raw_node is None else (node, kind, default)
        for declaration in group_sources:
            group_name = _selector(
                declaration.data.get("group"), declaration.origin.path + ("group",)
            )
            if group_name is not None:
                group_origin = declaration.field_origin("group")
                break
        group = _definition(groups, "group", group_name)
        data: dict[str, Any] = {}
        origins: dict[YamlPath, FieldOrigin] = {}
        declared: dict[YamlPath, list[FieldOrigin]] = {}

        for declaration in (default, kind, group, node):
            for key, value in declaration.data.items():
                if key in _NODE_ONLY and declaration.origin.level != "node":
                    continue
                for path, origin in _field_origins(declaration, (key,), value):
                    declared.setdefault(path, []).append(origin)
                if key in {"kind", "group"} or value is None:
                    continue
                if key in _STRING_FIELDS:
                    value = _selector(value, declaration.origin.path + (key,))
                    if value is None:
                        continue
                if key in _STRING_MAPS:
                    values = _mapping(
                        value, f"{'.'.join(map(str, declaration.origin.path))}.{key}"
                    )
                    merged = dict(data.get(key, {}))
                    for field, item in values.items():
                        # Go decodes these into map[string]string. Null is an
                        # empty override; a native bool becomes a bool-string.
                        if item is None:
                            item = ""
                        elif isinstance(item, bool):
                            item = "true" if item else "false"
                        elif isinstance(item, (int, float)):
                            item = str(item)
                        elif not isinstance(item, str):
                            raise TopologyError(
                                f"{'.'.join(map(str, declaration.origin.path))}.{key}.{field} must be a scalar string"
                            )
                        merged[field] = item
                        origins[(key, field)] = declaration.field_origin(key, field)
                    data[key] = merged
                    origins[(key,)] = declaration.field_origin(key)
                elif key in _MERGED_LISTS:
                    if not isinstance(value, (list, tuple)):
                        raise TopologyError(
                            f"{'.'.join(map(str, declaration.origin.path))}.{key} must be a list"
                        )
                    merged_list = list(data.get(key, ()))
                    for index, item in enumerate(value):
                        if item not in merged_list:
                            origins[(key, len(merged_list))] = declaration.field_origin(
                                key, index
                            )
                            merged_list.append(item)
                    data[key] = merged_list
                    origins[(key,)] = declaration.field_origin(key)
                elif (
                    value != ""
                    and not (key in _NUMBERS and value == 0)
                    and not (key == "ports" and not value)
                ):
                    data[key] = value
                    # Replacing a whole object must drop obsolete child origins.
                    for path in tuple(origins):
                        if path[:1] == (key,):
                            del origins[path]
                    origins.update(_field_origins(declaration, (key,), value))
        for key, value, selected_origin in (
            ("kind", kind_name, kind_origin),
            ("group", group_name, group_origin),
        ):
            if value is not None and selected_origin is not None:
                data[key] = value
                origins[(key,)] = selected_origin
        result.append(
            EffectiveNode(
                name,
                data,
                origins,
                {key: tuple(value) for key, value in declared.items()},
            )
        )
    return tuple(result)
