from __future__ import annotations

import argparse
import importlib.metadata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

FREEZE_CONTRIBUTOR_GROUP = "engulf_clab.freeze.v1"


class FreezeError(RuntimeError):
    """A contributor could not safely transform or restore its state."""


@dataclass(frozen=True, slots=True)
class FreezeContext:
    source_topology: Path
    staged_topology: Path
    source_root: Path
    staging_root: Path
    workspace_state: Path | None
    user_state: Path | None
    arguments: argparse.Namespace
    environment: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class DefrostContext:
    topology: Path
    staging_root: Path
    destination: Path
    metadata: Mapping[str, Any]
    arguments: argparse.Namespace
    environment: Mapping[str, str]
    user_state: Path | None = None


@runtime_checkable
class FreezeContributor(Protocol):
    """Namespaced, optional transformation hooks used by freeze format 2."""

    contributor_id: str

    def add_freeze_arguments(self, parser: argparse.ArgumentParser) -> None: ...

    def add_defrost_arguments(self, parser: argparse.ArgumentParser) -> None: ...

    def freeze(self, context: FreezeContext) -> Mapping[str, Any] | None: ...

    def defrost(self, context: DefrostContext) -> None: ...


def discover_contributors() -> tuple[FreezeContributor, ...]:
    """Load installed contributors deterministically, rejecting broken contracts."""
    found: list[FreezeContributor] = []
    for entry in sorted(
        importlib.metadata.entry_points(group=FREEZE_CONTRIBUTOR_GROUP),
        key=lambda item: item.name,
    ):
        candidate = entry.load()
        value = candidate() if isinstance(candidate, type) else candidate
        if not isinstance(value, FreezeContributor):
            raise FreezeError(
                f"freeze contributor {entry.name!r} has an invalid contract"
            )
        if entry.name != value.contributor_id:
            raise FreezeError(
                f"freeze contributor entry point {entry.name!r} does not match "
                f"{value.contributor_id!r}"
            )
        found.append(value)
    return tuple(found)
