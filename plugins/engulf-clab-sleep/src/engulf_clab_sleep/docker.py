from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .model import Container


class DockerError(RuntimeError):
    pass


class DockerClient:
    def containers(self) -> tuple[Container, ...]:
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
        payload = _json(
            self._run(("container", "inspect", *identifiers)),
            "container inspect",
        )
        if not isinstance(payload, list):
            raise DockerError("docker container inspect returned invalid JSON")
        result: list[Container] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            config = item.get("Config")
            state = item.get("State")
            labels = config.get("Labels") if isinstance(config, dict) else None
            labels = labels if isinstance(labels, dict) else {}
            lab = labels.get("containerlab")
            container_id = item.get("Id")
            image_id = item.get("Image")
            if not isinstance(lab, str) or not lab:
                continue
            if not isinstance(container_id, str) or not container_id:
                continue
            if not isinstance(image_id, str) or not image_id:
                continue
            topology_value = labels.get("clab-topo-file")
            topology = (
                Path(topology_value).resolve()
                if isinstance(topology_value, str) and topology_value
                else None
            )
            result.append(
                Container(
                    container_id,
                    lab,
                    topology,
                    image_id,
                    bool(state.get("Running")) if isinstance(state, dict) else False,
                )
            )
        return tuple(result)

    def resolve_images(self, references: Sequence[str]) -> dict[str, str]:
        resolved: dict[str, str] = {}
        for reference in dict.fromkeys(references):
            try:
                payload = _json(
                    self._run(("image", "inspect", reference)),
                    "image inspect",
                )
            except DockerError:
                continue
            if isinstance(payload, list) and payload and isinstance(payload[0], dict):
                image_id = payload[0].get("Id")
                if isinstance(image_id, str) and image_id:
                    resolved[reference] = image_id
        return resolved

    def available_images(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for image_id in self._run(
            ("image", "ls", "--all", "--no-trunc", "--quiet")
        ).split():
            result[image_id.removeprefix("sha256:")] = image_id
        return result

    def remove_container(self, container_id: str) -> None:
        self._run(("container", "rm", "--force", "--volumes", container_id))

    def remove_image(self, image_id: str) -> None:
        # Deliberately omit --force: Docker must protect non-lab consumers that
        # are outside the registry's ownership model.
        self._run(("image", "rm", image_id))

    def _run(self, arguments: Sequence[str]) -> str:
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


def _json(value: str, source: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as error:
        raise DockerError(f"docker {source} returned invalid JSON: {error}") from error
