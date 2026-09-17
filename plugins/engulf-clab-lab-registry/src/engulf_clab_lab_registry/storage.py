from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from engulf_api import StateStore
from engulf_clab_lab_registry_api import (
    LabRecord,
    LabRegistryError,
    RegistryCommit,
)

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

    The load-time snapshot is kept apart from the visitor view (``_base``) so
    that later upserts cannot move the fence base the owner compares against on
    commit.
    """

    def __init__(
        self,
        snapshot: tuple[LabRecord, ...] = (),
        *,
        persistent: bool = True,
        revision: int = 0,
    ) -> None:
        self._records = {item.key: item for item in snapshot}
        self._base = dict(self._records)
        self._pending: dict[tuple[str, Path], LabRecord] = {}
        self._persistent = persistent
        self._revision = revision

    @property
    def persistent(self) -> bool:
        """Whether pending updates may be written back to user state."""
        return self._persistent

    @property
    def revision(self) -> int:
        """Registry revision this session was loaded from (0 when unknown)."""
        return self._revision

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

    def base(self) -> dict[tuple[str, Path], LabRecord]:
        """Return the load-time snapshot the fenced commit compares against."""
        return self._base


class StateLabRegistry:
    """Lab registry backed by one plugin-owned Engulf user-state store.

    Only ``engulf_clab.lab_registry`` may use this, and only inside its own
    callbacks: the wrapped store is activation-bound.
    """

    def __init__(self, state: StateStore) -> None:
        self._state = state

    def records(self) -> tuple[LabRecord, ...]:
        return _read_payload(self._state)[0]

    def revision(self) -> int:
        return _read_payload(self._state)[1]

    def upsert(self, updates: tuple[LabRecord, ...]) -> None:
        _validate_updates(updates)
        if not updates:
            return
        with self._state.transaction() as locked:
            records, revision = _read_payload(locked)
            merged = {item.key: item for item in records}
            for update in updates:
                merged[update.key] = _merge_record(merged.get(update.key), update)
            _persist(locked, records, merged, revision)

    def commit(self, session: SessionLabRegistry) -> RegistryCommit:
        """Persist a session's pending updates under one fenced transaction.

        A session that was served from an unreadable file is never written, so
        the offending file survives for inspection. Otherwise every pending
        update is applied against the current on-disk entry for its key: when
        the entry still matches the session's load-time base, the normal merge
        runs; when another actor changed it concurrently, the newer on-disk
        entry wins and only monotone fields (topology, deployment history) are
        merged in. A concurrent writer therefore never loses its record to a
        stale flush.
        """
        if not session.persistent:
            return RegistryCommit(
                committed=False,
                revision=session.revision,
                error="lab registry is not persistent",
            )
        updates = session.pending()
        base = session.base()
        with self._state.transaction() as locked:
            records, revision = _read_payload(locked)
            merged = {item.key: item for item in records}
            for update in updates:
                current = merged.get(update.key)
                # Unchanged, or absent on disk entirely: apply the update
                # normally. Otherwise another actor moved this key.
                if current is None or current == base.get(update.key):
                    merged[update.key] = _merge_record(current, update)
                else:
                    merged[update.key] = _concurrent_win(current, update)
            revision, stored = _persist(locked, records, merged, revision)
        return RegistryCommit(True, revision, stored)


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


def _read_payload(
    state: StateStore,
) -> tuple[tuple[LabRecord, ...], int]:
    """Return the stored records and revision, or empty ones when absent."""
    if not state.exists(_FILENAME):
        return (), 0
    try:
        value = json.loads(state.read_text(_FILENAME))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise LabRegistryError("invalid lab registry") from error
    if not isinstance(value, dict) or value.get("version") != _VERSION:
        raise LabRegistryError("invalid lab registry")
    revision = value.get("revision", 0)
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
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
    return _sorted(parsed), revision


def _concurrent_win(current: LabRecord, update: LabRecord) -> LabRecord:
    """Keep a concurrently written entry, merging only monotone fields."""
    return LabRecord(
        current.name,
        current.directory,
        current.topology or update.topology,
        current.image_ids,
        current.ever_deployed or update.ever_deployed,
    )


def _persist(
    state: StateStore,
    records: tuple[LabRecord, ...],
    merged: Mapping[tuple[str, Path], LabRecord],
    revision: int,
) -> tuple[int, tuple[LabRecord, ...]]:
    """Write merged records, bumping the revision only on a content change.

    The comparison ignores the revision itself: two writes that produce the same
    lab set are the same registry state, so an idempotent retry (a crash before
    deletion, a re-run) must not advance the fence and invalidate a concurrent
    reader's plan. Returns the revision now in effect and the stored records.
    """
    stored = _sorted(merged.values())
    if stored == records:
        return revision, stored
    next_revision = revision + 1
    payload = {
        "version": _VERSION,
        "revision": next_revision,
        "labs": [_serialize(item) for item in stored],
    }
    rendered = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    state.write_text(_FILENAME, rendered)
    return next_revision, stored


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
