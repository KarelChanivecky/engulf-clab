from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .errors import SniffError

_INTERFACE = re.compile(r"^[A-Za-z0-9_.:/-]{1,15}$")


def topology_nodes(document: Mapping[str, Any]) -> tuple[str, ...]:
    topology = document.get("topology")
    if not isinstance(topology, Mapping):
        return ()
    nodes = topology.get("nodes")
    if not isinstance(nodes, Mapping):
        return ()
    return tuple(sorted(name for name in nodes if isinstance(name, str)))


def topology_lab_name(document: Mapping[str, Any], topology_path: Path) -> str:
    value = document.get("name")
    if isinstance(value, str) and value.strip():
        return value.strip()
    name = topology_path.name
    for suffix in (".clab.yaml", ".clab.yml", ".yaml", ".yml"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    if not name:
        raise SniffError("could not determine the Containerlab lab name")
    return name


def direct_peers(document: Mapping[str, Any], node: str) -> tuple[str, ...]:
    names = set(topology_nodes(document))
    if node not in names:
        return ()
    peers: set[str] = set()
    for endpoints in _link_endpoints(document):
        owners = tuple(_endpoint_owner(endpoint) for endpoint in endpoints)
        if node not in owners:
            continue
        peers.update(
            owner
            for owner in owners
            if owner is not None and owner in names and owner != node
        )
    return tuple(sorted(peers))


def linked_interfaces(
    document: Mapping[str, Any], node1: str, node2: str
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            left
            for left, _right in linked_interface_pairs(document, node1, node2)
        )
    )


def linked_interface_pairs(
    document: Mapping[str, Any], node1: str, node2: str
) -> tuple[tuple[str, str], ...]:
    """Return declared endpoint interfaces for each direct link in node order."""
    interfaces: list[tuple[str, str]] = []
    for endpoints in _link_endpoints(document):
        matches = [
            (_endpoint_owner(endpoint), _endpoint_interface(endpoint))
            for endpoint in endpoints
        ]
        left = tuple(interface for owner, interface in matches if owner == node1)
        right = tuple(interface for owner, interface in matches if owner == node2)
        if not left or not right:
            continue
        interfaces.extend(
            (left_interface, right_interface)
            for left_interface in left
            for right_interface in right
            if left_interface is not None and right_interface is not None
        )
    return tuple(dict.fromkeys(interfaces))


def _link_endpoints(document: Mapping[str, Any]) -> tuple[tuple[str, ...], ...]:
    topology = document.get("topology")
    if not isinstance(topology, Mapping):
        return ()
    links = topology.get("links")
    if not isinstance(links, Sequence) or isinstance(links, (str, bytes)):
        return ()
    result: list[tuple[str, ...]] = []
    for link in links:
        if not isinstance(link, Mapping):
            continue
        endpoints = link.get("endpoints")
        if not isinstance(endpoints, Sequence) or isinstance(endpoints, (str, bytes)):
            continue
        result.append(tuple(item for item in endpoints if isinstance(item, str)))
    return tuple(result)


def _endpoint_owner(endpoint: str) -> str | None:
    owner, separator, _interface = endpoint.partition(":")
    return owner if separator and owner else None


def _endpoint_interface(endpoint: str) -> str | None:
    _owner, separator, interface = endpoint.partition(":")
    if not separator or not _INTERFACE.fullmatch(interface):
        return None
    return interface


def choose_interface(
    document: Mapping[str, Any],
    node1: str,
    node2: str,
    requested: str | None,
) -> str:
    interfaces = linked_interfaces(document, node1, node2)
    if requested is not None:
        if requested not in interfaces:
            available = ", ".join(interfaces) or "none"
            raise SniffError(
                f"{requested!r} is not a {node1} interface directly linked to "
                f"{node2}; available: {available}"
            )
        return requested
    if not interfaces:
        raise SniffError(f"{node1!r} and {node2!r} have no direct node-to-node link")
    if len(interfaces) > 1:
        choices = ", ".join(interfaces)
        raise SniffError(
            f"{node1!r} and {node2!r} have multiple links; choose one with "
            f"--interface ({choices})"
        )
    return interfaces[0]
