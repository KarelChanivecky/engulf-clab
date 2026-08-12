from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from engulf_api import StateStore

from .errors import VrnetlabError

STATE_BASENAME = "vrnetlab-images.json"


@dataclass(frozen=True)
class BuildFingerprint:
    qcow2: str
    qcow2_name: str
    vrnetlab: str
    builder_type: str


def load_state(store: StateStore) -> dict[str, BuildFingerprint]:
    if not store.exists(STATE_BASENAME):
        return {}
    content = store.read_text(STATE_BASENAME)
    if not content.strip():
        return {}

    try:
        data: Any = json.loads(content)
    except json.JSONDecodeError as error:
        raise VrnetlabError(f"{STATE_BASENAME} is not valid JSON: {error}") from error
    if not isinstance(data, dict):
        raise VrnetlabError(f"{STATE_BASENAME} must contain a JSON object")

    records: dict[str, BuildFingerprint] = {}
    for image, value in data.items():
        if not isinstance(image, str) or not isinstance(value, dict):
            raise VrnetlabError(f"{STATE_BASENAME} contains an invalid image record")
        fields = ("qcow2", "qcow2_name", "vrnetlab", "builder_type")
        if any(not isinstance(value.get(field), str) for field in fields):
            raise VrnetlabError(f"{STATE_BASENAME} contains an invalid record for {image}")
        records[image] = BuildFingerprint(
            qcow2=value["qcow2"],
            qcow2_name=value["qcow2_name"],
            vrnetlab=value["vrnetlab"],
            builder_type=value["builder_type"],
        )
    return records


def save_state(store: StateStore, records: dict[str, BuildFingerprint]) -> None:
    data = {image: asdict(fingerprint) for image, fingerprint in sorted(records.items())}
    store.write_text(STATE_BASENAME, json.dumps(data, indent=2, sort_keys=True) + "\n")
