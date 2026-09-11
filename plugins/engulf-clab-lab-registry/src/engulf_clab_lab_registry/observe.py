from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from engulf_clab_lab_parser import load_topology
from engulf_clab_lab_registry_api import LabRecord, LabRegistryError


def observe_deployed_lab(
    topology: Path,
    environment: Mapping[str, str],
) -> LabRecord:
    document = load_topology(topology, environment)
    name = document.get("name")
    if not isinstance(name, str) or not name:
        raise LabRegistryError(f"topology has no nonempty name: {topology}")
    images: set[str] = set()
    for item in _containers():
        config = item.get("Config")
        labels = config.get("Labels") if isinstance(config, dict) else None
        labels = labels if isinstance(labels, dict) else {}
        if labels.get("containerlab") != name:
            continue
        topology_value = labels.get("clab-topo-file")
        if isinstance(topology_value, str) and topology_value:
            observed_topology = Path(topology_value).resolve()
            if observed_topology.parent != topology.parent:
                continue
        image_id = item.get("Image")
        if isinstance(image_id, str) and image_id:
            images.add(image_id)
    if not images:
        raise LabRegistryError(f"deployed lab {name!r} has no observable containers")
    return LabRecord(name, topology.parent, topology, frozenset(images), True)


def _containers() -> tuple[dict[str, Any], ...]:
    identifiers = _run(
        (
            "container",
            "ls",
            "--all",
            "--filter",
            "label=containerlab",
            "--quiet",
            "--no-trunc",
        )
    ).split()
    if not identifiers:
        return ()
    try:
        payload = json.loads(_run(("container", "inspect", *identifiers)))
    except json.JSONDecodeError as error:
        raise LabRegistryError(
            "docker container inspect returned invalid JSON"
        ) from error
    if not isinstance(payload, list):
        raise LabRegistryError("docker container inspect returned invalid JSON")
    return tuple(item for item in payload if isinstance(item, dict))


def _run(arguments: Sequence[str]) -> str:
    try:
        result = subprocess.run(
            ["docker", *arguments],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise LabRegistryError(f"could not run docker: {error}") from error
    if result.returncode:
        detail = (
            result.stderr.strip()
            or result.stdout.strip()
            or f"exit {result.returncode}"
        )
        raise LabRegistryError(f"docker {' '.join(arguments[:2])} failed: {detail}")
    return result.stdout
