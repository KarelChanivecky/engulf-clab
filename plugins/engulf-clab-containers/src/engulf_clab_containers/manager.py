from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from engulf_clab_containers_api import (
    ContainerDefinition,
    RegisteredContainerCollection,
    image_namespace,
)

from .errors import ContainersError

_NON_ALPHANUMERIC = re.compile(r"[^A-Z0-9]+")


@dataclass(frozen=True, slots=True)
class ManagedContainer:
    collection_id: str
    namespace: str
    definition: ContainerDefinition

    @property
    def image(self) -> str:
        return f"{self.namespace}/{self.definition.name}:latest"


def environment_prefix(application_name: str) -> str:
    prefix = _NON_ALPHANUMERIC.sub("_", application_name.upper()).strip("_")
    if not prefix:
        raise ContainersError(f"cannot derive environment prefix from {application_name!r}")
    return prefix


def application_prefix_name(application: object) -> str:
    short_name = getattr(application, "short_product_name", None)
    if isinstance(short_name, str) and short_name.strip():
        return short_name
    product = getattr(application, "product", None)
    if isinstance(product, str) and product.strip():
        return product
    raise ContainersError("application product metadata must be a nonempty string")


def catalog(
    collections: tuple[RegisteredContainerCollection, ...],
) -> tuple[ManagedContainer, ...]:
    owners: dict[str, str] = {}
    images: dict[str, ManagedContainer] = {}
    for collection in collections:
        namespace = image_namespace(collection.plugin_id)
        previous_owner = owners.get(namespace)
        if previous_owner is not None and previous_owner != collection.plugin_id:
            raise ContainersError(
                f"container namespace {namespace!r} is declared by both "
                f"{previous_owner!r} and {collection.plugin_id!r}"
            )
        owners[namespace] = collection.plugin_id
        names: set[str] = set()
        for definition in collection.containers:
            if definition.name in names:
                raise ContainersError(
                    f"collection {collection.plugin_id!r} declares container "
                    f"{definition.name!r} more than once"
                )
            names.add(definition.name)
            _validate_assets(collection.plugin_id, definition)
            managed = ManagedContainer(collection.plugin_id, namespace, definition)
            if managed.image in images:
                raise ContainersError(f"duplicate managed container image {managed.image}")
            images[managed.image] = managed
    return tuple(images[key] for key in sorted(images))


def _validate_assets(collection_id: str, definition: ContainerDefinition) -> None:
    dockerfile = definition.build.dockerfile
    context = definition.build.context
    if not dockerfile.is_file():
        raise ContainersError(
            f"collection {collection_id!r} Dockerfile does not exist: {dockerfile}"
        )
    if not context.is_dir():
        raise ContainersError(
            f"collection {collection_id!r} build context does not exist: {context}"
        )
    try:
        dockerfile.relative_to(context)
    except ValueError as error:
        raise ContainersError(
            f"collection {collection_id!r} Dockerfile must be inside its build context"
        ) from error


def matching_container(
    image: object, containers: tuple[ManagedContainer, ...]
) -> ManagedContainer | None:
    if not isinstance(image, str):
        return None
    by_canonical = {item.image: item for item in containers}
    by_untagged = {item.image.removesuffix(":latest"): item for item in containers}
    if image in by_canonical:
        return by_canonical[image]
    if image in by_untagged:
        return by_untagged[image]
    namespaces = {item.namespace for item in containers}
    namespace, separator, name_tag = image.partition("/")
    if separator and namespace in namespaces:
        name, tag_separator, tag = name_tag.partition(":")
        if any(item.namespace == namespace and item.definition.name == name for item in containers):
            if tag_separator and tag != "latest":
                raise ContainersError(
                    f"managed container {namespace}/{name} only supports tag latest"
                )
        else:
            raise ContainersError(
                f"active collection namespace {namespace!r} has no container {name!r}"
            )
    return None


def merged_fields(
    node_name: str,
    node: dict[str, Any],
    managed: ManagedContainer,
    *,
    prefix: str,
) -> dict[str, object]:
    requirements = managed.definition.node
    if requirements.requires_management:
        network_mode = node.get("network-mode")
        if network_mode is not None and network_mode != "bridge":
            raise ContainersError(
                f"node {node_name} requires its eth0 management interface; "
                f"network-mode {network_mode!r} is incompatible"
            )
    result: dict[str, object] = {
        "image": managed.image,
        "kind": _required_scalar(node_name, node, "kind", requirements.kind),
        "image-pull-policy": _required_scalar(node_name, node, "image-pull-policy", "Never"),
        "cap-add": _merged_list(node_name, node.get("cap-add"), requirements.cap_add),
        "sysctls": _merged_mapping(
            node_name, "sysctls", node.get("sysctls"), dict(requirements.sysctls)
        ),
    }
    environment = dict(requirements.environment)
    environment[f"{prefix}_DOCKERFILE"] = str(managed.definition.build.dockerfile)
    environment[f"{prefix}_DOCKER_CTX"] = str(managed.definition.build.context)
    result["env"] = _merged_mapping(node_name, "env", node.get("env"), environment)
    return result


def _required_scalar(node_name: str, node: dict[str, Any], key: str, required: object) -> object:
    current = node.get(key)
    if current is not None and current != required:
        raise ContainersError(
            f"node {node_name} {key} must be {required!r} for its managed container"
        )
    return required


def _merged_list(node_name: str, current: object, required: tuple[str, ...]) -> list[str]:
    if current is None:
        existing: list[str] = []
    elif isinstance(current, list) and all(isinstance(value, str) for value in current):
        existing = list(current)
    else:
        raise ContainersError(f"node {node_name} cap-add must be a list of strings")
    for value in required:
        if value not in existing:
            existing.append(value)
    return existing


def _merged_mapping(
    node_name: str,
    field: str,
    current: object,
    required: dict[str, str | int],
) -> dict[str, object]:
    if current is None:
        existing: dict[str, object] = {}
    elif isinstance(current, dict):
        existing = dict(current)
    else:
        raise ContainersError(f"node {node_name} {field} must be a YAML mapping")
    for key, value in required.items():
        if key in existing and existing[key] != value:
            raise ContainersError(
                f"node {node_name} {field}.{key} conflicts with required value {value!r}"
            )
        existing[key] = value
    return existing


def topology_nodes(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    topology = document.get("topology")
    if not isinstance(topology, dict):
        raise ContainersError("topology file is missing topology mapping")
    nodes = topology.get("nodes")
    if not isinstance(nodes, dict):
        raise ContainersError("topology file is missing topology.nodes mapping")
    result: dict[str, dict[str, Any]] = {}
    for name, value in nodes.items():
        if not isinstance(value, dict):
            raise ContainersError(f"node {name} must be a YAML mapping")
        result[str(name)] = value
    return result


def topology_edits(
    document: dict[str, Any],
    containers: tuple[ManagedContainer, ...],
    *,
    prefix: str,
) -> tuple[tuple[str, dict[str, object]], ...]:
    edits: list[tuple[str, dict[str, object]]] = []
    for name, node in topology_nodes(document).items():
        managed = matching_container(node.get("image"), containers)
        if managed is None:
            continue
        edits.append((name, merged_fields(name, node, managed, prefix=prefix)))
    return tuple(edits)


def format_catalog(containers: tuple[ManagedContainer, ...]) -> str:
    if not containers:
        return "No active container collections."
    width = max(len(item.image) for item in containers)
    lines = ["Active eclab container collection images:"]
    lines.extend(f"  {item.image:<{width}}  {item.definition.summary}" for item in containers)
    return "\n".join(lines)
