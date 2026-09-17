from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from engulf_api import InvocationAPI

LAB_REGISTRY_CONTEXT = "engulf_clab.lab_registry.registry"
LAB_REGISTRY_COMMIT_CONTEXT = "engulf_clab.lab_registry.commit"
LAB_REGISTRY_PLUGIN_ID = "engulf_clab.lab_registry"


class LabRegistryError(RuntimeError):
    """The shared lab registry is unavailable or contains invalid data."""


@dataclass(frozen=True, slots=True)
class Workspace:
    """An immutable, absolute and canonical lab workspace path."""

    path: Path

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path) or not self.path.is_absolute():
            raise ValueError("workspace path must be an absolute Path")
        object.__setattr__(self, "path", self.path.resolve())

    @property
    def directory(self) -> Path:
        """Return the canonical filesystem path represented by this value."""
        return self.path

    def __fspath__(self) -> str:
        return os.fspath(self.path)


@dataclass(frozen=True, slots=True)
class LabRecord:
    """One persistent lab identity and its last observed image ownership."""

    name: str
    workspace: Workspace
    topology: Path | None
    image_ids: frozenset[str]
    ever_deployed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("lab name must be a nonempty string")
        if isinstance(self.workspace, Path):
            # Accept the former constructor spelling at the boundary while
            # ensuring every stored record contains the value type.
            object.__setattr__(self, "workspace", Workspace(self.workspace))
        elif not isinstance(self.workspace, Workspace):
            raise TypeError("lab workspace must be a Workspace or Path")
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
    def directory(self) -> Path:
        """Return the canonical workspace path for filesystem consumers."""
        return self.workspace.path

    @property
    def key(self) -> tuple[str, Path]:
        return self.name, self.workspace.path


@dataclass(frozen=True, slots=True)
class RegistryCommit:
    """Outcome of persisting one invocation's registry observations.

    ``engulf_clab.lab_registry`` publishes this under
    ``LAB_REGISTRY_COMMIT_CONTEXT`` from its ``after_goal``. A destructive
    consumer that ordered itself to run later in the same phase reads it to
    learn whether its intent reached durable storage before it deletes anything.

    ``committed`` is false when nothing could be written, and then no delete may
    be attempted. ``revision`` is the revision the registry holds afterwards (or
    the session's load-time revision when nothing was written), and fences a
    decision that was planned against an earlier snapshot. ``records`` is the
    complete stored inventory when known, so a reader can re-derive ownership
    without a second read.
    """

    committed: bool
    revision: int
    records: tuple[LabRecord, ...] = ()
    error: str | None = None


@runtime_checkable
class LabRegistry(Protocol):
    """Capability-free view of the lab inventory for one invocation.

    Implementations must hold records, never an Engulf state handle: the value
    behind ``LAB_REGISTRY_CONTEXT`` is read by plugins in their own callbacks,
    where a handle captured by ``engulf_clab.lab_registry`` is no longer active.
    ``upsert`` therefore records intent in memory; ``engulf_clab.lab_registry``
    persists it from its own ``after_goal`` and publishes a ``RegistryCommit``.

    ``persistent`` reports whether the backing registry could be read and may be
    written at all; a destructive consumer must refuse to run when it is false
    rather than delete against an inventory it cannot confirm or preserve.
    ``revision`` is the registry revision the session was loaded from (``0``
    when unknown) and fences a decision planned against that snapshot.
    """

    @property
    def persistent(self) -> bool: ...

    @property
    def revision(self) -> int: ...

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
