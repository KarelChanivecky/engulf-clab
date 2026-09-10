from __future__ import annotations

import stat
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from engulf_clab_lab_parser import load_topology

from .docker import DockerClient, DockerError
from .model import Consumption, Container, ImageUsage, Lab


class ConsumptionError(RuntimeError):
    pass


def selected_lab(
    topology: Path,
    containers: Sequence[Container],
    docker: DockerClient,
    environment: Mapping[str, str],
) -> Lab:
    try:
        document = load_topology(topology, environment)
    except (OSError, RuntimeError) as error:
        raise ConsumptionError(str(error)) from error
    name = document.get("name")
    if not isinstance(name, str) or not name:
        raise ConsumptionError(f"topology has no nonempty name: {topology}")
    matching = tuple(
        item
        for item in containers
        if item.lab == name
        and (item.topology is None or item.topology.parent == topology.parent)
    )
    image_ids = {item.image_id for item in matching}
    if not image_ids:
        references = _topology_images(document)
        image_ids.update(docker.resolve_images(references).values())
    return Lab(
        name,
        topology.parent,
        frozenset(image_ids),
        tuple(item.container_id for item in matching if item.running),
    )


def running_labs(containers: Sequence[Container]) -> tuple[Lab, ...]:
    groups: dict[tuple[str, Path | None], list[Container]] = {}
    for item in containers:
        if not item.running:
            continue
        directory = item.topology.parent if item.topology is not None else None
        groups.setdefault((item.lab, directory), []).append(item)
    labs = (
        Lab(
            name,
            directory,
            frozenset(item.image_id for item in members),
            tuple(item.container_id for item in members),
        )
        for (name, directory), members in groups.items()
    )
    return tuple(sorted(labs, key=lambda item: (item.name, str(item.directory or ""))))


def collect(
    labs: Sequence[Lab],
    docker: DockerClient,
    *,
    image_usage: Mapping[str, ImageUsage] | None = None,
) -> tuple[Consumption, ...]:
    stats = docker.stats(tuple(identifier for lab in labs for identifier in lab.running_container_ids))
    usage = image_usage
    if usage is None:
        try:
            usage = docker.image_usage()
        except DockerError:
            usage = {}
    rows: list[Consumption] = []
    for lab in labs:
        runtime = [stats.get(identifier) for identifier in lab.running_container_ids]
        complete_runtime = all(item is not None for item in runtime)
        cpu = sum(item.cpu_percent for item in runtime if item is not None) if complete_runtime else None
        memory = sum(item.memory_bytes for item in runtime if item is not None) if complete_runtime else None
        if not lab.running_container_ids:
            cpu, memory = 0.0, 0
        directory = directory_size(lab.directory) if lab.directory is not None else None
        images = [_usage_for(image_id, usage) for image_id in lab.image_ids]
        complete_images = all(item is not None for item in images)
        split_available = complete_images and all(
            item is not None and item.unique is not None and item.shared is not None
            for item in images
        )
        unique = (
            sum(item.unique or 0 for item in images if item is not None)
            if split_available
            else None
        )
        shared = (
            sum(item.shared or 0 for item in images if item is not None)
            if split_available
            else None
        )
        if not lab.image_ids:
            unique, shared = 0, 0
            complete_images = True
        storage = (
            directory + sum(item.size for item in images if item is not None)
            if directory is not None and complete_images
            else None
        )
        rows.append(
            Consumption(
                lab.name,
                cpu,
                memory,
                directory,
                unique,
                shared,
                storage,
                lab.image_ids,
            )
        )
    return tuple(rows)


def classify_image_usage(
    usage: Mapping[str, ImageUsage], labs: Sequence[Lab]
) -> dict[str, ImageUsage]:
    """Classify an image's full size as shared when distinct labs use its ID."""
    owners: dict[str, set[tuple[str, Path | None]]] = defaultdict(set)
    for lab in labs:
        identity = (lab.name, lab.directory)
        for image_id in lab.image_ids:
            item = _usage_for(image_id, usage)
            if item is not None:
                owners[item.image_id].add(identity)
    result = dict(usage)
    for image_id, identities in owners.items():
        if len(identities) < 2:
            continue
        item = _usage_for(image_id, usage)
        if item is None:
            continue
        shared = ImageUsage(item.image_id, item.size, item.size, 0)
        for key, candidate in tuple(result.items()):
            if candidate.image_id == item.image_id:
                result[key] = shared
    return result


def totals(
    rows: Sequence[Consumption], image_usage: Mapping[str, ImageUsage]
) -> Consumption:
    image_ids = frozenset(identifier for row in rows for identifier in row.image_ids)
    images = [_usage_for(identifier, image_usage) for identifier in image_ids]
    complete_images = all(item is not None for item in images)
    split_available = complete_images and all(
        item is not None and item.unique is not None and item.shared is not None for item in images
    )
    directory = _sum_optional(row.directory_bytes for row in rows)
    unique = sum(item.unique or 0 for item in images if item is not None) if split_available else None
    shared = sum(item.shared or 0 for item in images if item is not None) if split_available else None
    if not image_ids:
        unique, shared, complete_images = 0, 0, True
    storage = (
        directory + sum(item.size for item in images if item is not None)
        if directory is not None and complete_images
        else None
    )
    return Consumption(
        "TOTAL",
        _sum_optional(row.cpu_percent for row in rows),
        _sum_optional(row.memory_bytes for row in rows),
        directory,
        unique,
        shared,
        storage,
        image_ids,
    )


def directory_size(root: Path) -> int | None:
    """Return allocated bytes without following symlinks or counting hard links twice."""
    seen: set[tuple[int, int]] = set()
    total = 0
    try:
        entries: Iterable[Path] = (root, *root.rglob("*"))
        for path in entries:
            metadata = path.lstat()
            identity = (metadata.st_dev, metadata.st_ino)
            if identity in seen:
                continue
            seen.add(identity)
            if stat.S_ISLNK(metadata.st_mode):
                continue
            total += metadata.st_blocks * 512
    except OSError:
        return None
    return total


def _usage_for(image_id: str, usage: Mapping[str, ImageUsage]) -> ImageUsage | None:
    normalized = image_id.removeprefix("sha256:")
    direct = usage.get(image_id) or usage.get(normalized)
    if direct is not None:
        return direct
    matches = {id(item): item for key, item in usage.items() if key.removeprefix("sha256:").startswith(normalized) or normalized.startswith(key.removeprefix("sha256:"))}
    return next(iter(matches.values())) if len(matches) == 1 else None


def _sum_optional(values: Iterable[int | float | None]) -> Any:
    materialized = tuple(values)
    return sum(value for value in materialized if value is not None) if all(value is not None for value in materialized) else None


def _topology_images(document: Mapping[str, Any]) -> tuple[str, ...]:
    topology = document.get("topology")
    nodes = topology.get("nodes") if isinstance(topology, dict) else None
    if not isinstance(nodes, dict):
        return ()
    defaults = document.get("defaults")
    defaults = defaults if isinstance(defaults, dict) else {}
    kinds = document.get("kinds")
    kinds = kinds if isinstance(kinds, dict) else {}
    values = []
    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        kind = node.get("kind", defaults.get("kind"))
        kind_defaults = kinds.get(kind) if isinstance(kind, str) else None
        kind_defaults = kind_defaults if isinstance(kind_defaults, dict) else {}
        image = node.get("image", kind_defaults.get("image", defaults.get("image")))
        if isinstance(image, str) and image:
            values.append(image)
    return tuple(dict.fromkeys(values))
