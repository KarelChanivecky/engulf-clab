"""Containerlab node-state health gate parsing and polling."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_KEY = "x-engulf-clab-health-gates"
_DEFAULT_TIMEOUT = 60.0
_DEFAULT_INTERVAL = 2.0


class HealthGateError(RuntimeError):
    """A node-health declaration is invalid or a node did not become ready."""


@dataclass(frozen=True, slots=True)
class NodeGate:
    node: str
    container: str
    timeout: float
    interval: float


def gates_from_topology(data: Mapping[str, Any], topology_path: Path) -> tuple[NodeGate, ...]:
    """Build a gate for each configured node, or every topology node by default."""
    value = data.get(_KEY)
    if value is None:
        return ()
    if not isinstance(value, Mapping):
        raise HealthGateError(f"{_KEY} must be a mapping")
    timeout = _number(value.get("timeout", _DEFAULT_TIMEOUT), "timeout")
    interval = _number(value.get("interval", _DEFAULT_INTERVAL), "interval")
    nodes = _topology_nodes(data)
    selected = value.get("nodes", tuple(nodes))
    if not isinstance(selected, Sequence) or isinstance(selected, (str, bytes)):
        raise HealthGateError(f"{_KEY}.nodes must be a list of node names")
    if any(not isinstance(node, str) or not node for node in selected):
        raise HealthGateError(f"{_KEY}.nodes must be a list of node names")
    unknown = set(selected) - set(nodes)
    if unknown:
        raise HealthGateError(f"health gate references unknown node(s): {', '.join(sorted(unknown))}")
    lab_name = _lab_name(data, topology_path)
    return tuple(
        NodeGate(
            node=node,
            container=f"clab-{lab_name}-{node}",
            timeout=timeout,
            interval=interval,
        )
        for node in selected
    )


def wait_for_gates(
    gates: Sequence[NodeGate],
    *,
    info: Callable[[str], None],
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    inspect: Callable[[str], tuple[str, str | None]] | None = None,
) -> None:
    """Wait until each container is running and its configured check is healthy."""
    node_state = inspect or _inspect
    for gate in gates:
        info(f"waiting for node {gate.node} to become running and healthy")
        deadline = now() + gate.timeout
        failure = "container is not ready"
        while True:
            try:
                status, health = node_state(gate.container)
                if status != "running":
                    raise HealthGateError(f"container state is {status}")
                if health is None:
                    raise HealthGateError("container has no Docker HEALTHCHECK status")
                if health != "healthy":
                    raise HealthGateError(f"container health is {health}")
                info(f"node {gate.node} is running and healthy")
                break
            except (HealthGateError, OSError) as error:
                failure = str(error)
                remaining = deadline - now()
                if remaining <= 0:
                    raise HealthGateError(
                        f"node {gate.node} did not become running and healthy "
                        f"after {gate.timeout:g}s: {failure}"
                    ) from error
                sleep(min(gate.interval, remaining))


def _topology_nodes(data: Mapping[str, Any]) -> tuple[str, ...]:
    topology = data.get("topology")
    if not isinstance(topology, Mapping) or not isinstance(topology.get("nodes"), Mapping):
        raise HealthGateError("topology.nodes must be a mapping")
    return tuple(str(name) for name in topology["nodes"] if isinstance(name, str) and name)


def _lab_name(data: Mapping[str, Any], topology_path: Path) -> str:
    name = data.get("name")
    if name is None:
        stem = topology_path.name
        for suffix in (".clab.yml", ".clab.yaml", ".yml", ".yaml"):
            if stem.endswith(suffix):
                return stem.removesuffix(suffix)
        return topology_path.stem
    if not isinstance(name, str) or not name:
        raise HealthGateError("topology name must be a nonempty string")
    return name


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise HealthGateError(f"{name} must be a positive number")
    return float(value)


def _inspect(container: str) -> tuple[str, str | None]:
    result = subprocess.run(
        [
            "docker",
            "inspect",
            "--format={{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}",
            container,
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode:
        detail = result.stderr.strip() or "container does not exist"
        raise OSError(detail)
    status, separator, health = result.stdout.strip().partition("|")
    if not separator or not status:
        raise OSError("docker returned an invalid container state")
    return status, health or None
