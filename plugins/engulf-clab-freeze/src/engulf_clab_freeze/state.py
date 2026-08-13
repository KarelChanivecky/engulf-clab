"""Workspace-scoped records of freeze archives that must not be re-archived."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from engulf_api import StateStore

STATE_FILENAME = "freeze-archives.json"
_STATE_VERSION = 1


class FreezeStateError(RuntimeError):
    """The managed freeze-archive state is invalid or unavailable."""


def tracked_archives(store: StateStore | None, root: Path) -> frozenset[Path]:
    """Return existing archive paths previously produced inside ``root``.

    Missing, non-file, and unsafe records are pruned while holding a short
    workspace-state transaction. Paths are stored relative to the workspace.
    """
    if store is None:
        return frozenset()
    workspace = root.resolve()
    with store.transaction() as locked:
        existed, records = _read_records(locked)
        retained = _retained_records(records, workspace)
        _save_records(locked, existed=existed, previous=records, records=retained)
    return frozenset(Path(record) for record in retained)


def track_archive(store: StateStore | None, root: Path, archive: Path) -> None:
    """Remember a newly requested archive when it is inside this workspace.

    Call this immediately before the final atomic rename. If the process stops
    before the archive appears, the next freeze prunes the temporary stale entry.
    """
    if store is None:
        return
    workspace = root.resolve()
    record = _record_for_archive(workspace, archive)
    if record is None:
        return
    with store.transaction() as locked:
        existed, records = _read_records(locked)
        retained = _retained_records(records, workspace, keep=frozenset({record}))
        if record not in retained:
            retained.append(record)
        retained.sort()
        _save_records(locked, existed=existed, previous=records, records=retained)


def _read_records(store: StateStore) -> tuple[bool, list[str]]:
    if not store.exists(STATE_FILENAME):
        return False, []
    try:
        raw: Any = json.loads(store.read_text(STATE_FILENAME))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FreezeStateError(f"{STATE_FILENAME} is not valid JSON") from error
    if (
        not isinstance(raw, dict)
        or raw.get("version") != _STATE_VERSION
        or not isinstance(raw.get("archives"), list)
        or any(not isinstance(item, str) for item in raw["archives"])
    ):
        raise FreezeStateError(f"{STATE_FILENAME} has an invalid schema")
    return True, list(raw["archives"])


def _retained_records(
    records: list[str], root: Path, *, keep: frozenset[str] = frozenset()
) -> list[str]:
    retained: set[str] = set()
    for record in records:
        normalized = _normalize_record(record)
        if normalized is None:
            continue
        if normalized in keep or _is_current_archive(root, normalized):
            retained.add(normalized)
    return sorted(retained)


def _normalize_record(value: str) -> str | None:
    if not value or "\x00" in value:
        return None
    path = Path(value)
    if path.is_absolute() or not path.parts or any(part in {".", ".."} for part in path.parts):
        return None
    return path.as_posix()


def _is_current_archive(root: Path, record: str) -> bool:
    candidate = root / record
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        return False
    return candidate.is_file() and resolved == candidate


def _record_for_archive(root: Path, archive: Path) -> str | None:
    try:
        relative = archive.resolve(strict=False).relative_to(root)
    except ValueError:
        return None
    return _normalize_record(relative.as_posix())


def _save_records(
    store: StateStore,
    *,
    existed: bool,
    previous: list[str],
    records: list[str],
) -> None:
    if records:
        if not existed or records != previous:
            store.write_text(
                STATE_FILENAME,
                json.dumps({"version": _STATE_VERSION, "archives": records}, sort_keys=True) + "\n",
            )
    elif existed:
        store.delete(STATE_FILENAME, missing_ok=True)
