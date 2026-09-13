from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass, replace
from typing import Any

from engulf_api import StateStore

from .allocation import Family, StickyIPError, allocation_prefix, private_network

REGISTRY_FILE = "sticky-ip.json"
REGISTRY_VERSION = 1
RESERVED_STATUSES = frozenset({"active", "pending", "uncertain"})


@dataclass(frozen=True, slots=True)
class Allocation:
    allocation_id: str
    lab_key: str
    workspace: str
    lab_name: str
    family: Family
    network_name: str
    subnet: str
    units: int
    node_ips: dict[str, str]
    status: str
    sequence: int
    managed: bool
    attempt_id: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.allocation_id,
            "lab": self.lab_key,
            "workspace": self.workspace,
            "name": self.lab_name,
            "family": self.family.value,
            "network": self.network_name,
            "subnet": self.subnet,
            "units": self.units,
            "node_ips": dict(sorted(self.node_ips.items())),
            "status": self.status,
            "sequence": self.sequence,
            "managed": self.managed,
            "attempt": self.attempt_id,
        }


@dataclass(frozen=True, slots=True)
class Registry:
    revision: int
    sequence: int
    cursors: dict[str, tuple[int, int]]
    allocations: tuple[Allocation, ...]

    @classmethod
    def empty(cls) -> Registry:
        return cls(0, 0, {Family.IPV4.value: (0, -1), Family.IPV6.value: (0, -1)}, ())

    def to_json(self) -> dict[str, Any]:
        return {
            "version": REGISTRY_VERSION,
            "revision": self.revision,
            "sequence": self.sequence,
            "cursors": {
                family: {"pool": cursor[0], "address": cursor[1]}
                for family, cursor in sorted(self.cursors.items())
            },
            "allocations": [item.to_json() for item in self.allocations],
        }


@dataclass(frozen=True, slots=True)
class Attempt:
    attempt_id: str
    lab_key: str
    allocation_id: str
    prior_ids: tuple[str, ...]
    evicted: tuple[Allocation, ...]


def load_registry(state: StateStore) -> Registry:
    if not state.exists(REGISTRY_FILE):
        return Registry.empty()
    try:
        value = json.loads(state.read_text(REGISTRY_FILE))
    except (OSError, json.JSONDecodeError) as error:
        raise StickyIPError(f"could not read sticky IP state: {error}") from error
    return _decode_registry(value)


def save_registry(state: StateStore, registry: Registry) -> None:
    state.write_text(REGISTRY_FILE, json.dumps(registry.to_json(), indent=2, sort_keys=True) + "\n")


def read_locked(state: StateStore) -> Registry:
    with state.transaction() as locked:
        return load_registry(locked)


def record_pending(
    state: StateStore,
    expected: Registry,
    allocation: Allocation,
    *,
    evicted: tuple[Allocation, ...] = (),
    cursor: tuple[int, int] | None = None,
) -> Attempt:
    with state.transaction() as locked:
        current = load_registry(locked)
        if current.revision != expected.revision:
            raise StickyIPError("sticky IP state changed while the host was being checked; retry")
        evicted_ids = {item.allocation_id for item in evicted}
        remaining = tuple(
            item for item in current.allocations if item.allocation_id not in evicted_ids
        )
        cursors = dict(current.cursors)
        if cursor is not None:
            cursors[allocation.family.value] = cursor
        updated = Registry(
            revision=current.revision + 1,
            sequence=max(current.sequence, allocation.sequence),
            cursors=cursors,
            allocations=(*remaining, allocation),
        )
        save_registry(locked, updated)
    prior_ids = tuple(
        item.allocation_id
        for item in expected.allocations
        if item.lab_key == allocation.lab_key and item.status in RESERVED_STATUSES
    )
    return Attempt(
        allocation.attempt_id or "",
        allocation.lab_key,
        allocation.allocation_id,
        prior_ids,
        evicted,
    )


def rollback_attempt(state: StateStore, attempt: Attempt) -> None:
    with state.transaction() as locked:
        current = load_registry(locked)
        target = next(
            (
                item
                for item in current.allocations
                if item.allocation_id == attempt.allocation_id
                and item.attempt_id == attempt.attempt_id
            ),
            None,
        )
        if target is None:
            return
        allocations = [
            item for item in current.allocations if item.allocation_id != target.allocation_id
        ]
        existing = {item.allocation_id for item in allocations}
        allocations.extend(item for item in attempt.evicted if item.allocation_id not in existing)
        save_registry(
            locked,
            replace(
                current,
                revision=current.revision + 1,
                allocations=tuple(allocations),
            ),
        )


def finish_attempt(state: StateStore, attempt: Attempt, *, success: bool) -> None:
    with state.transaction() as locked:
        current = load_registry(locked)
        found = False
        updated: list[Allocation] = []
        for item in current.allocations:
            if (
                item.allocation_id == attempt.allocation_id
                and item.attempt_id == attempt.attempt_id
            ):
                found = True
                updated.append(
                    replace(
                        item,
                        status="active" if success else "uncertain",
                        attempt_id=None,
                    )
                )
            elif success and item.allocation_id in attempt.prior_ids:
                updated.append(replace(item, status="inactive", attempt_id=None))
            else:
                updated.append(item)
        if found:
            save_registry(
                locked,
                replace(
                    current,
                    revision=current.revision + 1,
                    allocations=tuple(updated),
                ),
            )


def release_lab(state: StateStore, key: str) -> None:
    _release(state, key=key)


def release_all(state: StateStore) -> None:
    _release(state, key=None)


def _release(state: StateStore, *, key: str | None) -> None:
    with state.transaction() as locked:
        current = load_registry(locked)
        changed = False
        result: list[Allocation] = []
        for item in current.allocations:
            if (key is None or item.lab_key == key) and item.status in RESERVED_STATUSES:
                result.append(replace(item, status="inactive", attempt_id=None))
                changed = True
            else:
                result.append(item)
        if changed:
            save_registry(
                locked,
                replace(
                    current,
                    revision=current.revision + 1,
                    allocations=tuple(result),
                ),
            )


def _decode_registry(value: object) -> Registry:
    if not isinstance(value, dict) or value.get("version") != REGISTRY_VERSION:
        raise StickyIPError("sticky IP state has an unsupported format")
    revision = _integer(value.get("revision"), "revision", minimum=0)
    sequence = _integer(value.get("sequence"), "sequence", minimum=0)
    raw_cursors = value.get("cursors")
    if not isinstance(raw_cursors, dict):
        raise StickyIPError("sticky IP state has invalid cursors")
    cursors: dict[str, tuple[int, int]] = {}
    for family in Family:
        raw = raw_cursors.get(family.value, {"pool": 0, "address": -1})
        if not isinstance(raw, dict):
            raise StickyIPError("sticky IP state has invalid cursors")
        cursors[family.value] = (
            _integer(raw.get("pool"), "cursor pool", minimum=0),
            _integer(raw.get("address"), "cursor address", minimum=-1),
        )
    raw_allocations = value.get("allocations")
    if not isinstance(raw_allocations, list):
        raise StickyIPError("sticky IP state has invalid allocations")
    allocations = tuple(_decode_allocation(item) for item in raw_allocations)
    identifiers = {item.allocation_id for item in allocations}
    if len(identifiers) != len(allocations):
        raise StickyIPError("sticky IP state contains duplicate allocation IDs")
    return Registry(revision, sequence, cursors, allocations)


def _decode_allocation(value: object) -> Allocation:
    if not isinstance(value, dict):
        raise StickyIPError("sticky IP state contains an invalid allocation")
    strings = {}
    for key in ("id", "lab", "workspace", "name", "family", "network", "subnet", "status"):
        item = value.get(key)
        if not isinstance(item, str) or not item:
            raise StickyIPError("sticky IP state contains an invalid allocation")
        strings[key] = item
    try:
        family = Family(strings["family"])
    except ValueError as error:
        raise StickyIPError("sticky IP state contains an invalid family") from error
    status = strings["status"]
    if status not in RESERVED_STATUSES | {"inactive"}:
        raise StickyIPError("sticky IP state contains an invalid status")
    node_ips = value.get("node_ips")
    if not isinstance(node_ips, dict) or any(
        not isinstance(key, str) or not isinstance(item, str)
        for key, item in node_ips.items()
    ):
        raise StickyIPError("sticky IP state contains invalid node addresses")
    attempt = value.get("attempt")
    if attempt is not None and (not isinstance(attempt, str) or not attempt):
        raise StickyIPError("sticky IP state contains an invalid attempt")
    if status == "pending" and attempt is None:
        raise StickyIPError("sticky IP state contains a pending allocation without an attempt")
    if status != "pending" and attempt is not None:
        raise StickyIPError("sticky IP state contains an attempt on a completed allocation")
    try:
        subnet = ipaddress.ip_network(strings["subnet"], strict=True)
    except ValueError as error:
        raise StickyIPError("sticky IP state contains an invalid subnet") from error
    if subnet.version != family.version or not private_network(subnet):
        raise StickyIPError("sticky IP state contains a wrong-family or public subnet")
    units = _integer(value.get("units"), "allocation units", minimum=0)
    raw_managed = value.get("managed")
    if type(raw_managed) is not bool:
        raise StickyIPError("sticky IP state contains an invalid managed marker")
    managed = raw_managed
    if managed:
        if units == 0 or units & (units - 1) or subnet.prefixlen != allocation_prefix(family, units):
            raise StickyIPError("sticky IP state contains invalid managed allocation units")
    elif units != 0:
        raise StickyIPError("sticky IP state contains units for an explicit allocation")
    addresses = []
    try:
        addresses = [ipaddress.ip_address(item) for item in node_ips.values()]
    except ValueError as error:
        raise StickyIPError("sticky IP state contains an invalid node address") from error
    if (
        any(address.version != family.version or address not in subnet for address in addresses)
        or len(set(addresses)) != len(addresses)
    ):
        raise StickyIPError("sticky IP state contains invalid node addresses")
    return Allocation(
        strings["id"],
        strings["lab"],
        strings["workspace"],
        strings["name"],
        family,
        strings["network"],
        strings["subnet"],
        units,
        dict(node_ips),
        status,
        _integer(value.get("sequence"), "allocation sequence", minimum=0),
        managed,
        attempt,
    )


def _integer(value: object, label: str, *, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        raise StickyIPError(f"sticky IP state has invalid {label}")
    return value
