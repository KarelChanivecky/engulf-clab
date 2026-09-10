from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TextIO

from engulf_api import PluginLogger
from engulf_clab_lab_parser import topology_path_from_args

from .collector import (
    ConsumptionError,
    classify_image_usage,
    collect,
    running_labs,
    selected_lab,
    totals,
)
from .docker import DockerClient, DockerError
from .model import Consumption, Lab


def parser(program: str) -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog=program, description="Report resource consumption for eclab labs.")
    selection = result.add_mutually_exclusive_group()
    selection.add_argument("-t", "--topology", metavar="TOPOLOGY")
    selection.add_argument("--all", action="store_true", help="report every running lab")
    result.add_argument("-p", "--poll", action="store_true", help="refresh every two seconds")
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
                rendered = sample(
                    client,
                    topology=topology,
                    all_labs=options.all,
                    environment=environment,
                )
            except (ConsumptionError, DockerError) as problem:
                _error(logger, errors, program, problem)
                return 1
            if options.poll and destination.isatty():
                print("\x1b[2J\x1b[H", end="", file=destination)
            elif options.poll and not first:
                print(file=destination)
            print(rendered, file=destination, flush=True)
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
) -> str:
    containers = docker.containers()
    discovered = running_labs(containers)
    labs = discovered if all_labs else (
        selected_lab(_required(topology), containers, docker, environment),
    )
    try:
        image_usage = docker.image_usage(containers)
    except DockerError:
        image_usage = {}
    universe = _merge_labs((*discovered, *labs))
    image_usage = classify_image_usage(image_usage, universe)
    rows = collect(labs, docker, image_usage=image_usage)
    return render((*rows, totals(rows, image_usage)))


def _merge_labs(labs: Sequence[Lab]) -> tuple[Lab, ...]:
    merged: dict[tuple[str, Path | None], Lab] = {}
    for lab in labs:
        key = (lab.name, lab.directory)
        previous = merged.get(key)
        if previous is None:
            merged[key] = lab
            continue
        merged[key] = Lab(
            lab.name,
            lab.directory,
            previous.image_ids | lab.image_ids,
            tuple(dict.fromkeys((*previous.running_container_ids, *lab.running_container_ids))),
        )
    return tuple(merged.values())


def render(rows: Sequence[Consumption]) -> str:
    headings = ("LAB", "CPU", "RAM", "LAB DIR", "IMAGES UNIQUE", "IMAGES SHARED", "STORAGE")
    values = [
        (
            row.name,
            _cpu(row.cpu_percent),
            _bytes(row.memory_bytes),
            _bytes(row.directory_bytes),
            _bytes(row.unique_image_bytes),
            _bytes(row.shared_image_bytes),
            _bytes(row.storage_bytes),
        )
        for row in rows
    ]
    widths = [max(len(headings[index]), *(len(row[index]) for row in values)) for index in range(len(headings))]
    def line(row: Sequence[str]) -> str:
        return "  ".join(value.ljust(widths[index]) if index == 0 else value.rjust(widths[index]) for index, value in enumerate(row)).rstrip()
    result = [line(headings), line(tuple("-" * width for width in widths))]
    for index, row in enumerate(values):
        if index == len(values) - 1:
            result.append(line(tuple("-" * width for width in widths)))
        result.append(line(row))
    if any(row.shared_image_bytes not in (None, 0) for row in rows):
        result.append("Shared image bytes are deduplicated by image ID in TOTAL; totals may be smaller than row sums.")
    if any(None in (row.cpu_percent, row.memory_bytes, row.directory_bytes, row.unique_image_bytes, row.shared_image_bytes, row.storage_bytes) for row in rows):
        result.append("N/A means Docker or the filesystem did not provide a complete measurement.")
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
