from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from engulf_api import PluginLogger
from engulf_clab_lab_parser import load_topology, topology_path_from_args
from engulf_clab_lab_registry_api import LabRecord, LabRegistry, LabRegistryError

from .docker import DockerClient, DockerError
from .model import Container, LabUse, SleepPlan


class SleepError(RuntimeError):
    pass


def parser(program: str) -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog=program,
        description="Remove lab containers and reclaim lab-owned Docker images.",
    )
    selection = result.add_mutually_exclusive_group()
    selection.add_argument("-t", "--topology", metavar="TOPOLOGY")
    selection.add_argument(
        "--all",
        action="store_true",
        help="sleep every known lab, but only when all are destroyed",
    )
    result.add_argument(
        "--stopped",
        action="store_true",
        help="with --all, sleep only labs whose containers are stopped",
    )
    return result


def parse_options(arguments: Sequence[str], program: str) -> argparse.Namespace:
    argument_parser = parser(program)
    options = argument_parser.parse_args(list(arguments))
    if options.stopped and not options.all:
        argument_parser.error("--stopped requires --all")
    return options


def plan(
    arguments: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    registry: LabRegistry,
    docker: DockerClient,
    program: str = "eclab sleep",
    options: argparse.Namespace | None = None,
) -> SleepPlan:
    if options is None:
        options = parse_options(arguments, program)
    records = registry.records()
    containers = docker.containers()
    universe = _known_labs(records, containers)
    if options.all:
        if options.stopped:
            targets = tuple(
                lab
                for lab in universe
                if lab.container_ids and not lab.has_running_containers
            )
        else:
            deployed = tuple(lab for lab in universe if lab.container_ids)
            if deployed:
                names = ", ".join(lab.name for lab in deployed)
                raise SleepError(
                    "--all requires every known lab to be destroyed; "
                    f"containers remain for: {names}"
                )
            targets = universe
    else:
        try:
            topology = topology_path_from_args(
                (() if options.topology is None else ("-t", options.topology)), cwd
            )
            selected = _selected_lab(
                topology,
                environment,
                records,
                containers,
                docker,
            )
        except (OSError, RuntimeError) as error:
            raise SleepError(str(error)) from error
        universe = tuple(
            lab
            for lab in universe
            if not (lab.name == selected.name and lab.directory is None)
        )
        universe = _overlay((*universe, selected))
        targets = (selected,)

    target_keys = {lab.key for lab in targets}
    owners: dict[str, set[tuple[str, Path | None]]] = defaultdict(set)
    representative: dict[str, str] = {}
    for lab in universe:
        for image_id in lab.image_ids:
            normalized = _normalized(image_id)
            owners[normalized].add(lab.key)
            representative.setdefault(normalized, image_id)

    candidates = {
        _normalized(image_id) for lab in targets for image_id in lab.image_ids
    }
    if options.all and not options.stopped:
        deletable = candidates
        shared = set()
    else:
        shared = {image_id for image_id in candidates if owners[image_id] - target_keys}
        deletable = candidates - shared
    available = docker.available_images()
    image_ids = tuple(
        sorted(available[image_id] for image_id in deletable if image_id in available)
    )
    observations = tuple(
        LabRecord(
            lab.name,
            lab.directory,
            lab.topology,
            lab.image_ids,
            lab.ever_deployed,
        )
        for lab in targets
        if lab.directory is not None
    )
    return SleepPlan(
        targets,
        tuple(
            dict.fromkeys(
                container_id for lab in targets for container_id in lab.container_ids
            )
        ),
        image_ids,
        tuple(sorted(representative[item] for item in shared)),
        observations,
    )


def execute(
    sleep_plan: SleepPlan,
    *,
    registry: LabRegistry,
    docker: DockerClient,
    logger: PluginLogger,
) -> int:
    try:
        registry.upsert(sleep_plan.observations)
    except (OSError, RuntimeError, LabRegistryError) as error:
        logger.error("could not preserve labs in the registry before sleep: %s", error)
        return 1

    failures: list[str] = []
    removed_containers = 0
    removed_images = 0
    for container_id in sleep_plan.container_ids:
        try:
            docker.remove_container(container_id)
            removed_containers += 1
        except DockerError as error:
            failures.append(str(error))
    for image_id in sleep_plan.image_ids:
        try:
            docker.remove_image(image_id)
            removed_images += 1
        except DockerError as error:
            failures.append(str(error))

    for failure in failures:
        logger.error("%s", failure)
    logger.info(
        "slept %d lab(s): removed %d container(s) and %d image(s); preserved %d shared image(s)",
        len(sleep_plan.labs),
        removed_containers,
        removed_images,
        len(sleep_plan.preserved_shared_image_ids),
    )
    return 1 if failures else 0


def _known_labs(
    records: Sequence[LabRecord], containers: Sequence[Container]
) -> tuple[LabUse, ...]:
    labs = [
        LabUse(
            record.name,
            record.directory,
            record.topology,
            record.image_ids,
            (),
            record.ever_deployed,
            False,
        )
        for record in records
    ]
    groups: dict[tuple[str, Path | None], list[Container]] = defaultdict(list)
    for container in containers:
        directory = (
            container.topology.parent if container.topology is not None else None
        )
        groups[(container.lab, directory)].append(container)
    for (name, directory), members in groups.items():
        labs.append(
            LabUse(
                name,
                directory,
                next(
                    (item.topology for item in members if item.topology is not None),
                    None,
                ),
                frozenset(item.image_id for item in members),
                tuple(item.container_id for item in members),
                True,
                any(item.running for item in members),
            )
        )
    return _overlay(labs)


def _selected_lab(
    topology: Path,
    environment: Mapping[str, str],
    records: Sequence[LabRecord],
    containers: Sequence[Container],
    docker: DockerClient,
) -> LabUse:
    document = load_topology(topology, environment)
    name = document.get("name")
    if not isinstance(name, str) or not name:
        raise SleepError(f"topology has no nonempty name: {topology}")
    matching = tuple(
        item
        for item in containers
        if item.lab == name
        and (item.topology is None or item.topology.parent == topology.parent)
    )
    record = next(
        (
            item
            for item in records
            if item.name == name and item.directory == topology.parent
        ),
        None,
    )
    image_ids = frozenset(item.image_id for item in matching)
    if record is not None:
        image_ids |= record.image_ids
    image_ids |= frozenset(docker.resolve_images(_topology_images(document)).values())
    return LabUse(
        name,
        topology.parent,
        topology,
        image_ids,
        tuple(item.container_id for item in matching),
        bool(matching) or record is not None and record.ever_deployed,
        any(item.running for item in matching),
    )


def _overlay(labs: Sequence[LabUse]) -> tuple[LabUse, ...]:
    result: dict[tuple[str, Path | None], LabUse] = {}
    for lab in labs:
        previous = result.get(lab.key)
        if previous is None:
            result[lab.key] = lab
            continue
        result[lab.key] = LabUse(
            lab.name,
            lab.directory,
            lab.topology or previous.topology,
            previous.image_ids | lab.image_ids,
            tuple(dict.fromkeys((*previous.container_ids, *lab.container_ids))),
            previous.ever_deployed or lab.ever_deployed,
            previous.has_running_containers or lab.has_running_containers,
        )
    return tuple(
        sorted(result.values(), key=lambda item: (item.name, str(item.directory or "")))
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
    values: list[str] = []
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


def _normalized(image_id: str) -> str:
    return image_id.removeprefix("sha256:")
