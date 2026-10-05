from __future__ import annotations

import json
from typing import Any

from engulf_api import BeforeGoalAPI, InvocationAPI, StateScope
from engulf_clab_vrnetlab_build_api import (
    VrnetlabSourceProvenance,
    VrnetlabSourceProvenanceSnapshot,
)

STATE_BASENAME = "vrnetlab-source-provenance.json"
_STATE_VERSION = 1


def load_source_provenance(api: BeforeGoalAPI) -> VrnetlabSourceProvenanceSnapshot:
    state = api.state(StateScope.WORKSPACE)
    with state.transaction() as locked:
        if not locked.exists(STATE_BASENAME):
            return VrnetlabSourceProvenanceSnapshot()
        try:
            document: Any = json.loads(locked.read_text(STATE_BASENAME))
            if not isinstance(document, dict):
                raise TypeError("state root must be an object")
            if (
                type(document.get("version")) is not int
                or document.get("version") != _STATE_VERSION
            ):
                raise ValueError("state version is unsupported")
            values = document.get("sources")
            if not isinstance(values, list):
                raise TypeError("state sources must be a list")
            sources = tuple(_source_from_state(value) for value in values)
            return VrnetlabSourceProvenanceSnapshot(sources)
        except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError, ValueError) as error:
            api.logger.warning(
                "ignoring invalid vrnetlab source provenance workspace state: %s", error
            )
            return VrnetlabSourceProvenanceSnapshot()


def _source_from_state(value: Any) -> VrnetlabSourceProvenance:
    if not isinstance(value, dict):
        raise TypeError("vrnetlab source provenance entry must be an object")
    return VrnetlabSourceProvenance(
        node_name=value.get("node_name"),
        builder_type=value.get("builder_type"),
        source_provider_id=value.get("source_provider_id"),
        source_sha256=value.get("source_sha256"),
        source_path=value.get("source_path"),
    )


def save_source_provenance(
    api: InvocationAPI,
    snapshot: VrnetlabSourceProvenanceSnapshot,
) -> None:
    sources: list[dict[str, str | None]] = []
    for source in sorted(
        snapshot.sources,
        key=lambda item: (
            item.node_name,
            item.builder_type,
            item.source_provider_id or "",
            item.source_sha256,
        ),
    ):
        record: dict[str, str | None] = {
            "node_name": source.node_name,
            "builder_type": source.builder_type,
            "source_provider_id": source.source_provider_id,
            "source_sha256": source.source_sha256,
        }
        if source.source_path is not None:
            record["source_path"] = source.source_path
        sources.append(record)
    document = {"version": _STATE_VERSION, "sources": sources}
    state = api.state(StateScope.WORKSPACE)
    with state.transaction() as locked:
        locked.write_text(
            STATE_BASENAME,
            json.dumps(document, sort_keys=True, indent=2) + "\n",
        )
