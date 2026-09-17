from __future__ import annotations

import stat
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from engulf_clab_lab_parser import load_topology
from engulf_clab_lab_registry_api import LabRecord, Workspace

from .docker import DockerClient, DockerError
from .model import (
    Consumption,
    Container,
    ImageUsage,
    Lab,
    LabState,
    canonical_image_id,
)


class ConsumptionError(RuntimeError):
    pass


def selected_lab(
    topology: Path,
    containers: Sequence[Container],
    docker: DockerClient,
    environment: Mapping[str, str],
    record: LabRecord | None = None,
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
        and (
            item.topology is None
            or Workspace(item.topology.parent).path == Workspace(topology.parent).path
        )
    )
    image_ids = {canonical_image_id(item.image_id) for item in matching}
    if not image_ids:
        if record is not None and record.ever_deployed:
            image_ids.update(canonical_image_id(item) for item in record.image_ids)
        else:
            references = _topology_images(document)
            image_ids.update(
                canonical_image_id(item)
                for item in docker.resolve_images(references).values()
            )
    return Lab(
        name,
        topology.parent,
        frozenset(image_ids),
        tuple(item.container_id for item in matching if item.running),
        (
            LabState.DEPLOYED
            if any(item.running for item in matching)
            else LabState.STOPPED
            if matching
            else LabState.RECLAIMED
        ),
        topology,
    )


def deployed_labs(containers: Sequence[Container]) -> tuple[Lab, ...]:
    groups: dict[tuple[str, Path | None], list[Container]] = {}
    for item in containers:
        directory = item.topology.parent if item.topology is not None else None
        groups.setdefault((item.lab, directory), []).append(item)
    labs = (
        Lab(
            name,
            directory,
            frozenset(canonical_image_id(item.image_id) for item in members),
            tuple(item.container_id for item in members if item.running),
            (
                LabState.DEPLOYED
                if any(item.running for item in members)
                else LabState.STOPPED
            ),
            next(
                (item.topology for item in members if item.topology is not None), None
            ),
        )
        for (name, directory), members in groups.items()
    )
    return tuple(sorted(labs, key=lambda item: (item.name, str(item.directory or ""))))


def collect(
    labs: Sequence[Lab],
    docker: DockerClient,
    *,
    image_usage: Mapping[str, ImageUsage] | None = None,
    image_usage_available: bool = True,
) -> tuple[Consumption, ...]:
    stats = docker.stats(
        tuple(identifier for lab in labs for identifier in lab.running_container_ids)
    )
    usage = image_usage
    if usage is None:
        try:
            usage = docker.image_usage()
        except DockerError:
            usage = {}
            image_usage_available = False
    rows: list[Consumption] = []
    for lab in labs:
        runtime = [stats.get(identifier) for identifier in lab.running_container_ids]
        complete_runtime = all(item is not None for item in runtime)
        cpu = (
            sum(item.cpu_percent for item in runtime if item is not None)
            if complete_runtime
            else None
        )
        memory = (
            sum(item.memory_bytes for item in runtime if item is not None)
            if complete_runtime
            else None
        )
        if not lab.running_container_ids:
            cpu, memory = 0.0, 0
        directory = directory_size(lab.directory) if lab.directory is not None else None
        image_ids = frozenset(canonical_image_id(item) for item in lab.image_ids)
        images = [_usage_for(image_id, usage) for image_id in image_ids]
        missing_images_are_absent = (
            image_usage_available and lab.state is LabState.RECLAIMED
        )
        complete_images = image_usage_available and (
            missing_images_are_absent or all(item is not None for item in images)
        )
        split_available = complete_images and all(
            item is None or item.unique is not None and item.shared is not None
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
        if not image_ids:
            unique, shared = 0, 0
            complete_images = True
        storage = (
            directory + sum(item.size for item in images if item is not None)
            if directory is not None and complete_images
            else None
        )
        state = (
            LabState.DEPLOYED
            if lab.running_container_ids
            else LabState.RECLAIMED
            if unique == 0
            else LabState.STOPPED
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
                image_ids,
                state,
            )
        )
    return tuple(rows)


def classify_image_usage(
    usage: Mapping[str, ImageUsage], labs: Sequence[Lab]
) -> dict[str, ImageUsage]:
    """Classify complete image sizes by ownership across distinct labs."""
    owners: dict[str, set[tuple[str, Path | None]]] = defaultdict(set)
    for lab in labs:
        identity = (lab.name, lab.directory)
        for image_id in lab.image_ids:
            item = _usage_for(image_id, usage)
            if item is not None:
                owners[canonical_image_id(item.image_id)].add(identity)
    result = dict(usage)
    for image_id, identities in owners.items():
        item = _usage_for(image_id, usage)
        if item is None:
            continue
        classified = (
            ImageUsage(item.image_id, item.size, item.size, 0)
            if len(identities) >= 2
            else ImageUsage(item.image_id, item.size, 0, item.size)
        )
        for key, candidate in tuple(result.items()):
            if canonical_image_id(candidate.image_id) == image_id:
                result[key] = classified
    return result


def totals(
    rows: Sequence[Consumption],
    image_usage: Mapping[str, ImageUsage],
    *,
    image_usage_available: bool = True,
) -> Consumption:
    image_ids = frozenset(
        canonical_image_id(identifier) for row in rows for identifier in row.image_ids
    )
    images = [_usage_for(identifier, image_usage) for identifier in image_ids]
    absent_images = {
        identifier
        for identifier, image in zip(image_ids, images, strict=True)
        if image is None
    }
    safely_absent = all(
        row.state is LabState.RECLAIMED
        for identifier in absent_images
        for row in rows
        if identifier in {canonical_image_id(item) for item in row.image_ids}
    )
    complete_images = image_usage_available and (not absent_images or safely_absent)
    split_available = complete_images and all(
        item is None or item.unique is not None and item.shared is not None
        for item in images
    )
    directory = _sum_optional(row.directory_bytes for row in rows)
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
        None,
    )


def directory_size(root: Path) -> int | None:
    """Return allocated bytes without following symlinks or counting hard links twice."""
    seen: set[tuple[int, int]] = set()
    total = 0
    try:
        root.lstat()
    except FileNotFoundError:
        return 0
    except OSError:
        return None
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


def has_retained_resources(
    lab: Lab,
    image_usage: Mapping[str, ImageUsage],
    *,
    image_usage_available: bool,
) -> bool:
    if lab.state in {LabState.DEPLOYED, LabState.STOPPED}:
        return True
    if lab.directory is None:
        return True
    try:
        lab.directory.lstat()
    except FileNotFoundError:
        return not image_usage_available or any(
            _usage_for(canonical_image_id(image_id), image_usage) is not None
            for image_id in lab.image_ids
        )
    except OSError:
        return True
    return True


def _usage_for(image_id: str, usage: Mapping[str, ImageUsage]) -> ImageUsage | None:
    canonical = canonical_image_id(image_id)
    normalized = canonical.removeprefix("sha256:")
    direct = usage.get(image_id) or usage.get(canonical) or usage.get(normalized)
    if direct is not None:
        return direct
    matches = {
        id(item): item
        for key, item in usage.items()
        if canonical_image_id(key).startswith(canonical)
        or canonical.startswith(canonical_image_id(key))
    }
    return next(iter(matches.values())) if len(matches) == 1 else None


def _sum_optional(values: Iterable[int | float | None]) -> Any:
    materialized = tuple(values)
    return (
        sum(value for value in materialized if value is not None)
        if all(value is not None for value in materialized)
        else None
    )


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
