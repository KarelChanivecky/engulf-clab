from __future__ import annotations

import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from engulf_api import StateStore
from engulf_clab_lab_registry_api import LabRecord, LabRegistryError

_FILENAME = "labs.json"
_VERSION = 1


class SessionLabRegistry:
    """In-memory lab registry published for the span of one invocation.

    The published object deliberately captures no Engulf capability. State
    handles are bound to the activation of the callback that produced them, so a
    store published into shared context is dead as soon as its owner's callback
    returns; readers in their own callbacks would fail the activation guard.
    ``engulf_clab.lab_registry`` therefore loads the snapshot and writes pending
    updates back from its own callbacks, exactly as Docker image providers keep
    capability-free provider objects in shared context.
    """

    def __init__(
        self, snapshot: tuple[LabRecord, ...] = (), *, persistent: bool = True
    ) -> None:
        self._records = {item.key: item for item in snapshot}
        self._pending: dict[tuple[str, Path], LabRecord] = {}
        self._persistent = persistent

    @property
    def persistent(self) -> bool:
        """Whether pending updates may be written back to user state."""
        return self._persistent

    def records(self) -> tuple[LabRecord, ...]:
        return _sorted(self._records.values())

    def upsert(self, updates: tuple[LabRecord, ...]) -> None:
        _validate_updates(updates)
        for update in updates:
            merged = _merge_record(self._records.get(update.key), update)
            self._records[update.key] = merged
            self._pending[update.key] = merged

    def pending(self) -> tuple[LabRecord, ...]:
        """Return updates accumulated since load, for the owner to persist."""
        return _sorted(self._pending.values())


class StateLabRegistry:
    """Lab registry backed by one plugin-owned Engulf user-state store.

    Only ``engulf_clab.lab_registry`` may use this, and only inside its own
    callbacks: the wrapped store is activation-bound.
    """

    def __init__(self, state: StateStore) -> None:
        self._state = state

    def records(self) -> tuple[LabRecord, ...]:
        return _read_records(self._state)

    def upsert(self, updates: tuple[LabRecord, ...]) -> None:
        _validate_updates(updates)
        if not updates:
            return
        with self._state.transaction() as locked:
            merged = {item.key: item for item in _read_records(locked)}
            for update in updates:
                merged[update.key] = _merge_record(merged.get(update.key), update)
            payload = {
                "version": _VERSION,
                "labs": [_serialize(item) for item in _sorted(merged.values())],
            }
            rendered = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
            if locked.exists(_FILENAME) and locked.read_text(_FILENAME) == rendered:
                return
            locked.write_text(_FILENAME, rendered)


def _validate_updates(updates: tuple[LabRecord, ...]) -> None:
    if type(updates) is not tuple or any(
        not isinstance(item, LabRecord) for item in updates
    ):
        raise TypeError("lab registry updates must be a tuple of LabRecord values")


def _merge_record(previous: LabRecord | None, update: LabRecord) -> LabRecord:
    if previous is None:
        return update
    return LabRecord(
        update.name,
        update.directory,
        update.topology or previous.topology,
        update.image_ids,
        update.ever_deployed or previous.ever_deployed,
    )


def _sorted(records: Iterable[LabRecord]) -> tuple[LabRecord, ...]:
    return tuple(
        sorted(records, key=lambda item: (item.name, os.fspath(item.directory)))
    )


def _read_records(state: StateStore) -> tuple[LabRecord, ...]:
    if not state.exists(_FILENAME):
        return ()
    try:
        value = json.loads(state.read_text(_FILENAME))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise LabRegistryError("invalid lab registry") from error
    if not isinstance(value, dict) or value.get("version") != _VERSION:
        raise LabRegistryError("invalid lab registry")
    records = value.get("labs")
    if not isinstance(records, list):
        raise LabRegistryError("invalid lab registry")
    try:
        parsed = tuple(_parse_record(item) for item in records)
    except (TypeError, ValueError) as error:
        raise LabRegistryError("invalid lab registry record") from error
    if len({item.key for item in parsed}) != len(parsed):
        raise LabRegistryError("lab registry contains duplicate labs")
    return _sorted(parsed)


def _parse_record(value: Any) -> LabRecord:
    if not isinstance(value, dict):
        raise LabRegistryError("invalid lab registry record")
    name = value.get("name")
    directory = value.get("directory")
    topology = value.get("topology")
    image_ids = value.get("image_ids")
    ever_deployed = value.get("ever_deployed")
    if (
        not isinstance(name, str)
        or not isinstance(directory, str)
        or topology is not None
        and not isinstance(topology, str)
        or not isinstance(image_ids, list)
        or any(not isinstance(item, str) for item in image_ids)
        or not isinstance(ever_deployed, bool)
    ):
        raise LabRegistryError("invalid lab registry record")
    return LabRecord(
        name,
        Path(directory),
        Path(topology) if topology is not None else None,
        frozenset(image_ids),
        ever_deployed,
    )


def _serialize(record: LabRecord) -> dict[str, object]:
    return {
        "name": record.name,
        "directory": os.fspath(record.directory),
        "topology": os.fspath(record.topology) if record.topology is not None else None,
        "image_ids": sorted(record.image_ids),
        "ever_deployed": record.ever_deployed,
    }
