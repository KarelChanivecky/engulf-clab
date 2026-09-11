from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from engulf_api import StateStore
from engulf_clab_lab_registry_api import LabRecord, LabRegistryError

_FILENAME = "labs.json"
_VERSION = 1


class StateLabRegistry:
    """Lab registry backed by one plugin-owned Engulf user-state store."""

    def __init__(self, state: StateStore) -> None:
        self._state = state

    def records(self) -> tuple[LabRecord, ...]:
        return _read_records(self._state)

    def upsert(self, updates: tuple[LabRecord, ...]) -> None:
        if type(updates) is not tuple or any(
            not isinstance(item, LabRecord) for item in updates
        ):
            raise TypeError("lab registry updates must be a tuple of LabRecord values")
        if not updates:
            return
        with self._state.transaction() as locked:
            merged = {item.key: item for item in _read_records(locked)}
            for update in updates:
                previous = merged.get(update.key)
                if previous is None:
                    merged[update.key] = update
                    continue
                merged[update.key] = LabRecord(
                    update.name,
                    update.directory,
                    update.topology or previous.topology,
                    update.image_ids,
                    update.ever_deployed or previous.ever_deployed,
                )
            payload = {
                "version": _VERSION,
                "labs": [
                    _serialize(item)
                    for item in sorted(
                        merged.values(),
                        key=lambda item: (item.name, os.fspath(item.directory)),
                    )
                ],
            }
            rendered = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
            if locked.exists(_FILENAME) and locked.read_text(_FILENAME) == rendered:
                return
            locked.write_text(_FILENAME, rendered)


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
    return tuple(
        sorted(parsed, key=lambda item: (item.name, os.fspath(item.directory)))
    )


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
