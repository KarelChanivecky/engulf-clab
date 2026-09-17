from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from engulf_api import PluginLogger
from engulf_clab_lab_parser import topology_path_from_args
from engulf_clab_lab_registry_api import (
    LabRecord,
    LabRegistry,
    LabRegistryError,
    Workspace,
)

from .collector import (
    ConsumptionError,
    classify_image_usage,
    collect,
    deployed_labs,
    has_retained_resources,
    selected_lab,
    totals,
)
from .docker import DockerClient, DockerError
from .model import Consumption, Lab, LabState, canonical_image_id


@dataclass(frozen=True)
class Sample:
    rendered: str
    observations: tuple[LabRecord, ...]


def parser(program: str) -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog=program, description="Report resource consumption for eclab labs."
    )
    selection = result.add_mutually_exclusive_group()
    selection.add_argument("-t", "--topology", metavar="TOPOLOGY")
    selection.add_argument("--all", action="store_true", help="report every known lab")
    result.add_argument(
        "-p", "--poll", action="store_true", help="refresh every two seconds"
    )
    return result


def main(
    arguments: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    program: str = "eclab consumption",
    docker: DockerClient | None = None,
    output: TextIO | None = None,
    error: TextIO | None = None,
    sleep: Callable[[float], None] = time.sleep,
    logger: PluginLogger | None = None,
    registry: LabRegistry | None = None,
) -> int:
    destination = output or sys.stdout
    errors = error or sys.stderr
    options = parser(program).parse_args(list(arguments))
    client = docker or DockerClient()
    topology: Path | None = None
    if not options.all:
        try:
            topology = topology_path_from_args(
                (() if options.topology is None else ("-t", options.topology)), cwd
            )
        except RuntimeError as problem:
            _error(logger, errors, program, problem)
            return 2
    first = True
    try:
        while True:
            try:
                sampled = sample(
                    client,
                    topology=topology,
                    all_labs=options.all,
                    environment=environment,
                    records=registry.records() if registry is not None else (),
                )
            except (
                ConsumptionError,
                DockerError,
                OSError,
                LabRegistryError,
            ) as problem:
                _error(logger, errors, program, problem)
                return 1
            if registry is not None and sampled.observations:
                try:
                    registry.upsert(sampled.observations)
                except (OSError, RuntimeError) as problem:
                    _warning(
                        logger,
                        errors,
                        program,
                        f"could not update lab registry: {problem}",
                    )
            if options.poll and destination.isatty():
                print("\x1b[2J\x1b[H", end="", file=destination)
            elif options.poll and not first:
                print(file=destination)
            print(sampled.rendered, file=destination, flush=True)
            first = False
            if not options.poll:
                return 0
            sleep(2)
    except KeyboardInterrupt:
        return 0


def sample(
    docker: DockerClient,
    *,
    topology: Path | None,
    all_labs: bool,
    environment: Mapping[str, str],
    records: Sequence[LabRecord] = (),
) -> Sample:
    containers = docker.containers()
    discovered = deployed_labs(containers)
    indexed = tuple(_lab_from_record(record) for record in records)
    base_universe = _overlay_labs((*indexed, *discovered))
    if all_labs:
        labs = base_universe
        observations = tuple(
            _record_for_lab(lab, _find_record(records, lab))
            for lab in discovered
            if lab.directory is not None
        )
    else:
        required = _required(topology)
        document_lab = selected_lab(required, containers, docker, environment)
        record = _find_record(records, document_lab)
        selected = (
            selected_lab(
                required,
                containers,
                docker,
                environment,
                record=record,
            )
            if record is not None and record.ever_deployed
            else document_lab
        )
        labs = (selected,)
        observations = (_record_for_lab(selected, record, topology=required),)
    universe = _overlay_labs((*base_universe, *labs))
    try:
        image_usage = docker.image_usage(containers)
        image_usage_available = True
    except DockerError:
        image_usage = {}
        image_usage_available = False
    image_usage = classify_image_usage(image_usage, universe)
    if all_labs:
        labs = tuple(
            lab
            for lab in labs
            if has_retained_resources(
                lab,
                image_usage,
                image_usage_available=image_usage_available,
            )
        )
    rows = collect(
        labs,
        docker,
        image_usage=image_usage,
        image_usage_available=image_usage_available,
    )
    total = totals(
        rows,
        image_usage,
        image_usage_available=image_usage_available,
    )
    return Sample(render((*rows, total)), observations)


def _overlay_labs(labs: Sequence[Lab]) -> tuple[Lab, ...]:
    merged: dict[tuple[str, Path | None], Lab] = {}
    for lab in labs:
        key = (lab.name, lab.directory)
        merged[key] = lab
    return tuple(
        sorted(merged.values(), key=lambda item: (item.name, str(item.directory or "")))
    )


def _lab_from_record(record: LabRecord) -> Lab:
    return Lab(
        record.name,
        record.workspace.path,
        frozenset(canonical_image_id(item) for item in record.image_ids),
        (),
        LabState.RECLAIMED,
        record.topology,
    )


def _find_record(records: Sequence[LabRecord], lab: Lab) -> LabRecord | None:
    return next(
        (
            record
            for record in records
            if record.name == lab.name and record.workspace.path == lab.directory
        ),
        None,
    )


def _record_for_lab(
    lab: Lab,
    previous: LabRecord | None,
    *,
    topology: Path | None = None,
) -> LabRecord:
    if lab.directory is None:
        raise ConsumptionError(
            f"cannot index lab without a topology directory: {lab.name}"
        )
    return LabRecord(
        lab.name,
        Workspace(lab.directory),
        topology
        or (previous.topology if previous is not None else None)
        or lab.topology,
        lab.image_ids,
        lab.state is LabState.DEPLOYED
        or lab.state is LabState.STOPPED
        or previous is not None
        and previous.ever_deployed,
    )


def render(rows: Sequence[Consumption]) -> str:
    headings = (
        "LAB",
        "STATE",
        "CPU",
        "RAM",
        "LAB DIR",
        "IMAGES UNIQUE",
        "IMAGES SHARED",
        "STORAGE",
    )
    values = [
        (
            row.name,
            row.state.value if row.state is not None else "—",
            _cpu(row.cpu_percent),
            _bytes(row.memory_bytes),
            _bytes(row.directory_bytes),
            _bytes(row.unique_image_bytes),
            _bytes(row.shared_image_bytes),
            _bytes(row.storage_bytes),
        )
        for row in rows
    ]
    widths = [
        max(len(headings[index]), *(len(row[index]) for row in values))
        for index in range(len(headings))
    ]

    def line(row: Sequence[str]) -> str:
        return "  ".join(
            value.ljust(widths[index]) if index == 0 else value.rjust(widths[index])
            for index, value in enumerate(row)
        ).rstrip()

    result = [line(headings), line(tuple("-" * width for width in widths))]
    for index, row in enumerate(values):
        if index == len(values) - 1:
            result.append(line(tuple("-" * width for width in widths)))
        result.append(line(row))
    if any(row.shared_image_bytes not in (None, 0) for row in rows):
        result.append(
            "Shared image bytes are deduplicated by image ID in TOTAL; totals may be smaller than row sums."
        )
    if any(
        None
        in (
            row.cpu_percent,
            row.memory_bytes,
            row.directory_bytes,
            row.unique_image_bytes,
            row.shared_image_bytes,
            row.storage_bytes,
        )
        for row in rows
    ):
        result.append(
            "N/A means Docker or the filesystem did not provide a complete measurement."
        )
    return "\n".join(result)


def _required(value: Path | None) -> Path:
    if value is None:
        raise ConsumptionError("a topology is required")
    return value


def _error(
    logger: PluginLogger | None,
    destination: TextIO,
    program: str,
    problem: BaseException,
) -> None:
    if logger is None:
        print(f"{program}: {problem}", file=destination)
    else:
        logger.error("%s: %s", program, problem)


def _warning(
    logger: PluginLogger | None,
    destination: TextIO,
    program: str,
    message: str,
) -> None:
    if logger is None:
        print(f"{program}: warning: {message}", file=destination)
    else:
        logger.warning("%s: %s", program, message)


def _cpu(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}%"


def _bytes(value: int | None) -> str:
    if value is None:
        return "N/A"
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    amount = float(value)
    unit = units[0]
    for unit in units:
        if abs(amount) < 1024 or unit == units[-1]:
            break
        amount /= 1024
    return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.2f} {unit}"
