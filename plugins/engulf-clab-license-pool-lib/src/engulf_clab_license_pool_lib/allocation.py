from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .api import PoolManagerRequest, PoolManagerResult

LICENSE_POOL_REGISTRY_FILE = "license-pools.json"
LICENSE_POOL_STATE_VERSION = 3
LICENSE_ALLOCATION_HANDOFF_CONTEXT = "engulf_clab.license_pool.allocation_handoff"


class LicensePoolError(RuntimeError):
    """Raised when a persisted pool entry or allocation request is invalid."""


class LicenseStrategy(StrEnum):
    STICKY = "sticky"
    ROUND_ROBIN = "round-robin"
    LEAST_RECENTLY_USED = "least-recently-used"


@dataclass(frozen=True, slots=True)
class AllocationRequest:
    claim: str
    clamp: str | None = None


@dataclass(frozen=True, slots=True)
class AllocationResult:
    path: str
    created: bool


@dataclass(frozen=True, slots=True)
class RegisteredPool:
    """A pool registered for automatic allocation, in registration order."""

    path: str
    kind: str


@dataclass(frozen=True, slots=True)
class LicenseAllocationHandoff:
    """Marks an invocation as fully handled by another allocation provider."""

    provider_id: str


@dataclass(slots=True)
class PoolState:
    allocations: dict[str, str] = field(default_factory=dict)
    history: dict[str, str] = field(default_factory=dict)
    clamped: list[str] = field(default_factory=list)
    round_robin_index: int = 0
    last_used: dict[str, int] = field(default_factory=dict)
    usage_sequence: int = 0

    @classmethod
    def empty(cls) -> PoolState:
        return cls()

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> PoolState:
        result = cls(
            allocations=dict(value.get("allocations", {})),
            history=dict(value.get("history", {})),
            clamped=list(value.get("clamped", [])),
            round_robin_index=value.get("round_robin_index", 0),
            last_used=dict(value.get("last_used", {})),
            usage_sequence=value.get("usage_sequence", 0),
        )
        if (
            any(not isinstance(k, str) or not isinstance(v, str) for k, v in result.allocations.items())
            or any(not isinstance(k, str) or not isinstance(v, str) for k, v in result.history.items())
            or any(not isinstance(v, str) for v in result.clamped)
            or any(not isinstance(k, str) or type(v) is not int or v < 0 for k, v in result.last_used.items())
            or type(result.round_robin_index) is not int
            or result.round_robin_index < 0
            or type(result.usage_sequence) is not int
            or result.usage_sequence < 0
            or any(v > result.usage_sequence for v in result.last_used.values())
        ):
            raise LicensePoolError("invalid license-pool state")
        return result

    def to_mapping(self) -> dict[str, Any]:
        return {
            "allocations": dict(self.allocations),
            "history": dict(self.history),
            "clamped": list(self.clamped),
            "round_robin_index": self.round_robin_index,
            "last_used": dict(self.last_used),
            "usage_sequence": self.usage_sequence,
        }


class LicensePoolManager:
    """Public adapter for the shared registered-pool and claim registry.

    ``state`` is intentionally duck-typed: callers provide the Engulf user
    state store, while this library owns the file format and registry rules.
    Allocation callers must hold the same per-pool leases as the standard
    plugin around multi-pool operations.
    """

    def __init__(self, state: Any):
        self._state = state

    def register(self, pool: str | Path, kind: str) -> bool:
        canonical = str(Path(pool).expanduser().resolve())
        if re.fullmatch(r"[a-z0-9][a-z0-9_-]*", kind) is None:
            raise LicensePoolError("license pool kind must be a lowercase Containerlab kind token")
        with self._state.transaction() as locked:
            registry = _load_registry(locked)
            for entry in registry["registrations"]:
                if entry["path"] == canonical:
                    entry["kind"] = kind
                    _write_registry(locked, registry)
                    return False
            registry["registrations"].append({"path": canonical, "kind": kind})
            _write_registry(locked, registry)
        return True

    def remove(self, pool: str | Path) -> bool:
        """Remove one registered pool without changing its allocation history."""
        canonical = str(Path(pool).expanduser().resolve())
        with self._state.transaction() as locked:
            registry = _load_registry(locked)
            retained = [
                entry for entry in registry["registrations"]
                if entry["path"] != canonical
            ]
            changed = len(retained) != len(registry["registrations"])
            if changed:
                registry["registrations"] = retained
                _write_registry(locked, registry)
            return changed

    def manage(self, store: Any, request: "PoolManagerRequest") -> "PoolManagerResult":
        """Register one discovered pool and leave later-manager control to callers."""
        from .api import PoolManagerResult

        if store is not self:
            raise LicensePoolError("license pool manager must manage its own store")
        changed = self.register(request.path, request.kind)
        return PoolManagerResult(changed=changed)

    def registered_pools(self) -> tuple[RegisteredPool, ...]:
        with self._state.transaction() as locked:
            registry = _load_registry(locked)
            registrations = registry["registrations"]
            retained = [entry for entry in registrations if Path(entry["path"]).is_dir()]
            if retained != registrations:
                registry["registrations"] = retained
                _write_registry(locked, registry)
        return tuple(RegisteredPool(entry["path"], entry["kind"]) for entry in retained)

    def release_claims(self, claims: tuple[tuple[str, str, str], ...]) -> None:
        if not claims:
            return
        with self._state.transaction() as locked:
            registry = _load_registry(locked)
            for pool, path, claim in claims:
                entry = registry["pools"].get(pool)
                if isinstance(entry, dict) and entry.get("allocations", {}).get(path) == claim:
                    del entry["allocations"][path]
            _write_registry(locked, registry)

    def release_workspace(self, workspace: str) -> None:
        with self._state.transaction() as locked:
            registry = _load_registry(locked)
            for entry in registry["pools"].values():
                entry["allocations"] = {
                    path: claim
                    for path, claim in entry["allocations"].items()
                    if not claim.startswith(workspace + ":")
                }
            _write_registry(locked, registry)

    def release_all(self) -> None:
        with self._state.transaction() as locked:
            registry = _load_registry(locked)
            for entry in registry["pools"].values():
                entry["allocations"] = {}
            _write_registry(locked, registry)


def _new_pool_entry() -> dict[str, Any]:
    return {
        "allocations": {},
        "history": {},
        "clamped": [],
        "round_robin_index": 0,
        "last_used": {},
        "usage_sequence": 0,
    }


# Compatibility name for consumers of the original registry API.
LicensePoolRegistry = LicensePoolManager


def _load_registry(state: Any) -> dict[str, Any]:
    if not state.exists(LICENSE_POOL_REGISTRY_FILE):
        return {"version": LICENSE_POOL_STATE_VERSION, "pools": {}, "registrations": []}
    value = json.loads(state.read_text(LICENSE_POOL_REGISTRY_FILE))
    if not isinstance(value, dict) or not isinstance(value.get("pools"), dict):
        raise LicensePoolError("invalid license-pool state")
    if value.get("version") == 1:
        for entry in value["pools"].values():
            if not isinstance(entry, dict) or not isinstance(entry.get("history"), dict):
                raise LicensePoolError("invalid license-pool state")
            entry["round_robin_index"] = 0
            entry["last_used"] = {path: 0 for path in entry["history"]}
            entry["usage_sequence"] = 0
        value["version"] = 2
    if value.get("version") == 2:
        value["registrations"] = []
        value["version"] = LICENSE_POOL_STATE_VERSION
    if value.get("version") != LICENSE_POOL_STATE_VERSION:
        raise LicensePoolError("invalid license-pool state")
    registrations = value.get("registrations")
    if not isinstance(registrations, list):
        raise LicensePoolError("invalid license-pool state")
    seen: set[str] = set()
    for registration in registrations:
        if (
            not isinstance(registration, dict)
            or not isinstance(registration.get("path"), str)
            or not registration["path"]
            or not isinstance(registration.get("kind"), str)
            or re.fullmatch(r"[a-z0-9][a-z0-9_-]*", registration["kind"]) is None
            or registration["path"] in seen
        ):
            raise LicensePoolError("invalid license-pool state")
        seen.add(registration["path"])
    for entry in value["pools"].values():
        PoolState.from_mapping(entry)
    return value


def _write_registry(state: Any, value: dict[str, Any]) -> None:
    state.write_text(LICENSE_POOL_REGISTRY_FILE, json.dumps(value, sort_keys=True) + "\n")


def coerce_strategy(value: LicenseStrategy | str) -> LicenseStrategy:
    try:
        return LicenseStrategy(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(strategy.value for strategy in LicenseStrategy)
        raise LicensePoolError(f"license pool strategy must be one of: {choices}") from error
