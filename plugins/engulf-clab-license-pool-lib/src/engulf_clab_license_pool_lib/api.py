from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .allocation import (
    AllocationRequest,
    AllocationResult,
    LicenseStrategy,
    PoolState,
    RegisteredPool,
)


@dataclass(frozen=True, slots=True)
class PoolManagerRequest:
    """The normalized pool-management request supplied to a manager."""

    path: Path
    kind: str


@dataclass(frozen=True, slots=True)
class PoolManagerResult:
    """Result of one manager; preempt stops later managers from running."""

    preempt: bool = False
    changed: bool = False


class PoolManagerStore(Protocol):
    """Mutable pool registration surface shared by pool managers."""

    def registered_pools(self) -> tuple[RegisteredPool, ...]: ...

    def register(self, pool: str | Path, kind: str) -> bool: ...

    def remove(self, pool: str | Path) -> bool: ...


class PoolManager(Protocol):
    """Discover and persist pools for an init-pool request."""

    def manage(
        self,
        store: PoolManagerStore,
        request: PoolManagerRequest,
    ) -> PoolManagerResult: ...


class PoolSelector(Protocol):
    """Select one license from one already-discovered pool."""

    def select(
        self,
        state: PoolState,
        *,
        files: Sequence[str],
        request: AllocationRequest,
        strategy: LicenseStrategy | str,
    ) -> AllocationResult | None: ...


def run_pool_managers(
    managers: Sequence[PoolManager],
    store: PoolManagerStore,
    request: PoolManagerRequest,
) -> PoolManagerResult:
    """Run managers in order and stop before the next one when preempted."""
    changed = False
    preempted = False
    for manager in managers:
        result = manager.manage(store, request)
        changed = changed or result.changed
        if result.preempt:
            preempted = True
            break
    return PoolManagerResult(preempt=preempted, changed=changed)
