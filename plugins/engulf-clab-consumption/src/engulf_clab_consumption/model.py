from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Container:
    container_id: str
    lab: str
    topology: Path | None
    image_id: str
    image_ref: str
    running: bool
    retained_image_bytes: int | None = None


@dataclass(frozen=True)
class ImageUsage:
    image_id: str
    size: int
    shared: int | None
    unique: int | None


@dataclass(frozen=True)
class RuntimeStats:
    cpu_percent: float
    memory_bytes: int


@dataclass(frozen=True)
class Lab:
    name: str
    directory: Path | None
    image_ids: frozenset[str]
    running_container_ids: tuple[str, ...]


@dataclass(frozen=True)
class Consumption:
    name: str
    cpu_percent: float | None
    memory_bytes: int | None
    directory_bytes: int | None
    unique_image_bytes: int | None
    shared_image_bytes: int | None
    storage_bytes: int | None
    image_ids: frozenset[str]
