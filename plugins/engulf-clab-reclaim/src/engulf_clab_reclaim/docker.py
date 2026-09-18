from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from engulf_host_exec import docker_command

from .model import Container


class DockerError(RuntimeError):
    pass


_SIZE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([kmgtpe]?i?b)\s*$", re.IGNORECASE)
_DECIMAL = {
    "b": 1,
    "kb": 1000,
    "mb": 1000**2,
    "gb": 1000**3,
    "tb": 1000**4,
    "pb": 1000**5,
    "eb": 1000**6,
}
_BINARY = {
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
    "tib": 1024**4,
    "pib": 1024**5,
    "eib": 1024**6,
}
_RECLAIM_STORAGE_TYPES = frozenset({"images", "containers", "local volumes"})


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

    def storage_bytes(self) -> int:
        records = _records(self._run(("system", "df", "--format", "json")))
        found = False
        total = 0
        for item in records:
            category = item.get("Type")
            if (
                not isinstance(category, str)
                or category.casefold() not in _RECLAIM_STORAGE_TYPES
            ):
                continue
            size = _parse_size(item.get("Size"))
            if size is None:
                raise DockerError(
                    f"docker system df returned an invalid size for {category}"
                )
            found = True
            total += size
        if not found:
            raise DockerError("docker system df returned no storage records")
        return total

    def remove_container(self, container_id: str) -> bool:
        return self._run_removal(("container", "rm", "--force", "--volumes", container_id))

    def remove_image(self, image_id: str) -> bool:
        # Deliberately omit --force: Docker must protect non-lab consumers that
        # are outside the registry's ownership model.
        try:
            references = self._image_references(image_id)
        except DockerError as error:
            if _already_gone(str(error)):
                return False
            raise
        return self._run_removal(("image", "rm", *(references or (image_id,))))

    def _image_references(self, image_id: str) -> tuple[str, ...]:
        payload = _json(
            self._run(("image", "inspect", image_id)),
            "image inspect",
        )
        if not isinstance(payload, list) or not payload or not isinstance(
            payload[0], dict
        ):
            raise DockerError("docker image inspect returned invalid JSON")
        references: list[str] = []
        for field in ("RepoTags", "RepoDigests"):
            values = payload[0].get(field)
            if not isinstance(values, list):
                continue
            for value in values:
                if (
                    isinstance(value, str)
                    and value
                    and value != "<none>:<none>"
                    and value not in references
                ):
                    references.append(value)
        return tuple(references)

    def _run_removal(self, arguments: Sequence[str]) -> bool:
        """Run one removal, tolerating an object that is already gone.

        A crashed earlier attempt can leave a container or image removed after
        its record was written, so a retry must treat "no such object" as
        success instead of failing the run.
        """
        try:
            self._run(arguments)
        except DockerError as error:
            if _already_gone(str(error)):
                return False
            raise
        return True

    def _run(self, arguments: Sequence[str]) -> str:
        try:
            result = subprocess.run(
                docker_command(["docker", *arguments]),
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


def _already_gone(detail: str) -> bool:
    folded = detail.casefold()
    return "no such container" in folded or "no such image" in folded


def _json(value: str, source: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as error:
        raise DockerError(f"docker {source} returned invalid JSON: {error}") from error


def _records(output: str) -> tuple[dict[str, Any], ...]:
    stripped = output.strip()
    if not stripped:
        return ()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, list):
        values: list[Any] = payload
    elif isinstance(payload, dict):
        values = [payload]
    else:
        values = []
        for line in stripped.splitlines():
            try:
                values.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise DockerError(
                    f"docker system df returned invalid JSON: {error}"
                ) from error
    return tuple(item for item in values if isinstance(item, dict))


def _parse_size(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value if value >= 0 else None
    if not isinstance(value, str):
        return None
    match = _SIZE.fullmatch(value)
    if match is None:
        return None
    unit = match.group(2).casefold()
    multiplier = _BINARY.get(unit, _DECIMAL.get(unit))
    return None if multiplier is None else round(float(match.group(1)) * multiplier)
