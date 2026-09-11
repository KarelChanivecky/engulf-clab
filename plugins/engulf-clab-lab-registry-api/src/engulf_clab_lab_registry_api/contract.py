from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from engulf_api import InvocationAPI

LAB_REGISTRY_CONTEXT = "engulf_clab.lab_registry.registry"
LAB_REGISTRY_PLUGIN_ID = "engulf_clab.lab_registry"


class LabRegistryError(RuntimeError):
    """The shared lab registry is unavailable or contains invalid data."""


@dataclass(frozen=True, slots=True)
class LabRecord:
    """One persistent lab identity and its last observed image ownership."""

    name: str
    directory: Path
    topology: Path | None
    image_ids: frozenset[str]
    ever_deployed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("lab name must be a nonempty string")
        if not isinstance(self.directory, Path) or not self.directory.is_absolute():
            raise ValueError("lab directory must be an absolute Path")
        if self.topology is not None and (
            not isinstance(self.topology, Path) or not self.topology.is_absolute()
        ):
            raise ValueError("lab topology must be an absolute Path or None")
        if type(self.image_ids) is not frozenset or any(
            not isinstance(item, str) or not item for item in self.image_ids
        ):
            raise TypeError("lab image IDs must be a frozenset of nonempty strings")
        if type(self.ever_deployed) is not bool:
            raise TypeError("lab ever_deployed must be a boolean")

    @property
    def key(self) -> tuple[str, Path]:
        return self.name, self.directory


@runtime_checkable
class LabRegistry(Protocol):
    """Invocation-bound access to the persistent lab inventory."""

    def records(self) -> tuple[LabRecord, ...]: ...

    def upsert(self, records: tuple[LabRecord, ...]) -> None: ...


def lab_registry(api: InvocationAPI) -> LabRegistry:
    """Return the active lab registry or fail with an actionable error."""
    value = api.get_context(LAB_REGISTRY_CONTEXT)
    if not isinstance(value, LabRegistry):
        raise LabRegistryError(
            "lab registry is unavailable; install and activate engulf-clab-lab-registry"
        )
    return value
