from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .model import Container, ImageUsage, RuntimeStats

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


class DockerError(RuntimeError):
    pass


def parse_size(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value if value >= 0 else None
    if not isinstance(value, str) or value.strip().upper() in {"N/A", "--", ""}:
        return None
    match = _SIZE.fullmatch(value)
    if match is None:
        return None
    unit = match.group(2).lower()
    multiplier = _BINARY.get(unit, _DECIMAL.get(unit))
    return None if multiplier is None else round(float(match.group(1)) * multiplier)


class DockerClient:
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
            self._run(("container", "inspect", "--size", *identifiers)),
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
            if not isinstance(lab, str) or not lab:
                continue
            topology_value = labels.get("clab-topo-file")
            topology = (
                Path(topology_value).resolve()
                if isinstance(topology_value, str) and topology_value
                else None
            )
            image_id = item.get("Image")
            image_ref = config.get("Image") if isinstance(config, dict) else ""
            container_id = item.get("Id")
            if not isinstance(container_id, str) or not container_id:
                continue
            if not isinstance(image_id, str) or not image_id:
                continue
            rootfs_size = _nonnegative_int(item.get("SizeRootFs"))
            writable_size = _nonnegative_int(item.get("SizeRw"))
            retained_image_bytes = (
                max(0, rootfs_size - writable_size)
                if rootfs_size is not None and writable_size is not None
                else None
            )
            result.append(
                Container(
                    container_id,
                    lab,
                    topology,
                    image_id,
                    image_ref if isinstance(image_ref, str) else "",
                    bool(state.get("Running")) if isinstance(state, dict) else False,
                    retained_image_bytes,
                )
            )
        return tuple(result)

    def resolve_images(self, references: Sequence[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        for reference in dict.fromkeys(references):
            try:
                payload = _json(
                    self._run(("image", "inspect", reference)), "image inspect"
                )
            except DockerError:
                continue
            if isinstance(payload, list) and payload and isinstance(payload[0], dict):
                image_id = payload[0].get("Id")
                if isinstance(image_id, str) and image_id:
                    result[reference] = image_id
        return result

    def image_usage(
        self, containers: Sequence[Container] = ()
    ) -> dict[str, ImageUsage]:
        output = self._run(("system", "df", "--verbose", "--format", "json"))
        records = _records(output)
        result: dict[str, ImageUsage] = {}
        for item in records:
            image_id = _first(item, "ID", "Id", "ImageID", "ImageId")
            if not isinstance(image_id, str) or not image_id:
                continue
            size = parse_size(_first(item, "Size", "SIZE"))
            shared = parse_size(
                _first(item, "SharedSize", "Shared Size", "SHARED SIZE")
            )
            unique = parse_size(
                _first(item, "UniqueSize", "Unique Size", "UNIQUE SIZE")
            )
            if size is None and shared is not None and unique is not None:
                size = shared + unique
            if size is None:
                continue
            result[image_id] = ImageUsage(image_id, size, shared, unique)
            result[image_id.removeprefix("sha256:")] = result[image_id]
        retained: dict[str, int] = {}
        for container in containers:
            if container.retained_image_bytes is None:
                continue
            normalized = container.image_id.removeprefix("sha256:")
            retained[normalized] = max(
                retained.get(normalized, 0), container.retained_image_bytes
            )
        for normalized, size in retained.items():
            if _usage_for_id(normalized, result) is not None:
                continue
            fallback = ImageUsage(f"sha256:{normalized}", size, None, None)
            result[fallback.image_id] = fallback
            result[normalized] = fallback
        return result

    def stats(self, container_ids: Sequence[str]) -> dict[str, RuntimeStats]:
        if not container_ids:
            return {}
        try:
            output = self._run(
                (
                    "stats",
                    "--no-stream",
                    "--no-trunc",
                    "--format",
                    "json",
                    *container_ids,
                )
            )
        except DockerError:
            # A container may stop between discovery and stats. Let this sample
            # expose N/A; the next poll rediscovers the running set.
            return {}
        result: dict[str, RuntimeStats] = {}
        for item in _records(output):
            container_id = _first(item, "ID", "Container")
            cpu = _percent(_first(item, "CPUPerc", "CPU %"))
            memory_usage = _first(item, "MemUsage", "Mem Usage")
            memory = (
                parse_size(memory_usage.partition("/")[0])
                if isinstance(memory_usage, str)
                else None
            )
            if isinstance(container_id, str) and cpu is not None and memory is not None:
                result[container_id] = RuntimeStats(cpu, memory)
        return result


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
    values: list[Any]
    if isinstance(payload, list):
        values = payload
    elif isinstance(payload, dict):
        images = payload.get("Images") or payload.get("ImageUsage")
        if isinstance(images, dict):
            images = images.get("Items")
        values = images if isinstance(images, list) else [payload]
    else:
        values = []
        for line in stripped.splitlines():
            try:
                values.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise DockerError(
                    f"docker returned invalid JSON output: {error}"
                ) from error
    return tuple(item for item in values if isinstance(item, dict))


def _first(item: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in item:
            return item[name]
    return None


def _percent(value: object) -> float | None:
    if not isinstance(value, str):
        return float(value) if isinstance(value, (int, float)) else None
    try:
        return float(value.strip().removesuffix("%"))
    except ValueError:
        return None


def _nonnegative_int(value: object) -> int | None:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else None
    )


def _usage_for_id(image_id: str, usage: dict[str, ImageUsage]) -> ImageUsage | None:
    normalized = image_id.removeprefix("sha256:")
    direct = usage.get(image_id) or usage.get(normalized)
    if direct is not None:
        return direct
    matches = {
        id(item): item
        for key, item in usage.items()
        if key.removeprefix("sha256:").startswith(normalized)
        or normalized.startswith(key.removeprefix("sha256:"))
    }
    return next(iter(matches.values())) if len(matches) == 1 else None
