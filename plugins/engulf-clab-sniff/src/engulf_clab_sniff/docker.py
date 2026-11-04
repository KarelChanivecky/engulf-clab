from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import SniffError


@dataclass(frozen=True, slots=True)
class NodeContainer:
    identifier: str
    topology: Path | None
    running: bool
    network_mode: str


class DockerError(RuntimeError):
    """Docker CLI operation failed or returned malformed data."""


class DockerClient:
    def containers_for_lab(self, lab_name: str) -> tuple[Mapping[str, Any], ...]:
        identifiers = self._run(
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
        payload = self._json(
            self._run(("container", "inspect", *identifiers)),
            "docker container inspect",
        )
        if not isinstance(payload, list):
            raise DockerError("docker container inspect returned invalid JSON")
        return tuple(
            item
            for item in payload
            if isinstance(item, Mapping)
            and isinstance(item.get("Config"), Mapping)
            and isinstance(item["Config"].get("Labels"), Mapping)
            and item["Config"]["Labels"].get("containerlab") == lab_name
        )

    def find_node(
        self,
        *,
        lab_name: str,
        node_name: str,
        topology_path: Path,
    ) -> NodeContainer:
        matches: list[NodeContainer] = []
        for item in self.containers_for_lab(lab_name):
            config = item.get("Config")
            labels = config.get("Labels") if isinstance(config, Mapping) else None
            state = item.get("State")
            host_config = item.get("HostConfig")
            if (
                not isinstance(labels, Mapping)
                or labels.get("clab-node-name") != node_name
            ):
                continue
            identifier = item.get("Id")
            if not isinstance(identifier, str) or not identifier:
                continue
            source = labels.get("clab-topo-file")
            try:
                source_path = (
                    Path(source).resolve()
                    if isinstance(source, str) and source
                    else None
                )
            except (OSError, RuntimeError):
                source_path = None
            running = isinstance(state, Mapping) and state.get("Running") is True
            network_mode = (
                host_config.get("NetworkMode", "")
                if isinstance(host_config, Mapping)
                else ""
            )
            matches.append(
                NodeContainer(
                    identifier,
                    source_path,
                    running,
                    network_mode if isinstance(network_mode, str) else "",
                )
            )

        exact = tuple(
            item for item in matches if item.topology == topology_path.resolve()
        )
        running_exact = tuple(item for item in exact if item.running)
        running_matches = tuple(item for item in matches if item.running)
        candidates = running_exact or running_matches or exact or tuple(matches)
        if not candidates:
            raise SniffError(
                f"running Containerlab node {node_name!r} was not found in lab {lab_name!r}"
            )
        if len(candidates) > 1:
            raise SniffError(
                f"multiple deployed containers match node {node_name!r} in lab "
                f"{lab_name!r}; destroy duplicate lab deployments first"
            )
        result = candidates[0]
        if not result.running:
            raise SniffError(f"Containerlab node {node_name!r} is not running")
        if result.network_mode == "host":
            raise SniffError(
                f"node {node_name!r} uses host networking; sniff requires a private node namespace"
            )
        return result

    @staticmethod
    def _run(arguments: Sequence[str]) -> str:
        try:
            result = subprocess.run(
                ["docker", *arguments],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as error:
            raise DockerError(f"could not run docker: {error}") from error
        if result.returncode:
            detail = (
                result.stderr.strip()
                or result.stdout.strip()
                or f"exit {result.returncode}"
            )
            raise DockerError(f"docker {' '.join(arguments[:2])} failed: {detail}")
        return result.stdout

    @staticmethod
    def _json(output: str, operation: str) -> object:
        try:
            return json.loads(output)
        except json.JSONDecodeError as error:
            raise DockerError(f"{operation} returned invalid JSON") from error
