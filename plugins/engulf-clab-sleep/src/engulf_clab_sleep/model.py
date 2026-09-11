from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from engulf_clab_lab_registry_api import LabRecord


@dataclass(frozen=True, slots=True)
class Container:
    container_id: str
    lab: str
    topology: Path | None
    image_id: str
    running: bool = False


@dataclass(frozen=True, slots=True)
class LabUse:
    name: str
    directory: Path | None
    topology: Path | None
    image_ids: frozenset[str]
    container_ids: tuple[str, ...]
    ever_deployed: bool
    has_running_containers: bool = False

    @property
    def key(self) -> tuple[str, Path | None]:
        return self.name, self.directory


@dataclass(frozen=True, slots=True)
class SleepPlan:
    labs: tuple[LabUse, ...]
    container_ids: tuple[str, ...]
    image_ids: tuple[str, ...]
    preserved_shared_image_ids: tuple[str, ...]
    observations: tuple[LabRecord, ...]
