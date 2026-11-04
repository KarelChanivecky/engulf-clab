from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from importlib.resources import files
from types import MappingProxyType

GENERIC_VM_KIND = "generic_vm"


@lru_cache(maxsize=1)
def load_node_kind_map() -> Mapping[str, str]:
    """Load the packaged vrnetlab builder-to-Containerlab-kind mapping."""
    resource = files("engulf_clab_vrnetlab_build").joinpath("vrnetlab-kind-map.json")
    try:
        decoded = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"could not load vrnetlab node-kind map: {error}") from error
    if not isinstance(decoded, dict) or any(
        not isinstance(builder_type, str)
        or not builder_type.strip()
        or not isinstance(node_kind, str)
        or not node_kind.strip()
        for builder_type, node_kind in decoded.items()
    ):
        raise RuntimeError("vrnetlab node-kind map must contain nonempty string pairs")
    return MappingProxyType(decoded)


def expected_node_kind(builder_type: str) -> str:
    """Return the Containerlab kind expected for a vrnetlab builder path."""
    return load_node_kind_map().get(builder_type.strip().lower(), GENERIC_VM_KIND)
