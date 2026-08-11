from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from engulf_api import StateStore

from .errors import WanError

REGISTRY_FILENAME = "dhcp-wan-registry.json"
REGISTRY_VERSION = 1


def load_registry(state: StateStore) -> dict[str, Any]:
    if not state.exists(REGISTRY_FILENAME):
        return {"version": REGISTRY_VERSION, "bridges": {}}

    try:
        data: Any = json.loads(state.read_text(REGISTRY_FILENAME))
    except json.JSONDecodeError as error:
        raise WanError(f"{REGISTRY_FILENAME} is not valid JSON: {error}") from error
    if (
        not isinstance(data, dict)
        or data.get("version") != REGISTRY_VERSION
        or not isinstance(data.get("bridges"), dict)
    ):
        raise WanError(f"{REGISTRY_FILENAME} has an invalid schema")
    return data


def save_registry(state: StateStore, registry: Mapping[str, Any]) -> None:
    state.write_text(
        REGISTRY_FILENAME,
        json.dumps(registry, indent=2, sort_keys=True) + "\n",
    )


def claim_bridge(
    state: StateStore,
    *,
    workspace: str,
    configuration: Mapping[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """Record a workspace claim and return whether host provisioning is needed."""
    name = configuration["name"]
    if not isinstance(name, str):
        raise WanError("WAN bridge configuration is missing a name")

    with state.transaction() as locked:
        registry = load_registry(locked)
        bridges = registry["bridges"]
        assert isinstance(bridges, dict)
        existing = bridges.get(name)
        if existing is None:
            entry = {
                "configuration": dict(configuration),
                "journal": [],
                "status": "provisioning",
                "workspaces": [workspace],
            }
            bridges[name] = entry
            save_registry(locked, registry)
            return True, entry

        if not isinstance(existing, dict):
            raise WanError(f"WAN registry entry for {name} is invalid")
        if existing.get("configuration") != dict(configuration):
            raise WanError(
                f"WAN bridge {name} is already claimed with a conflicting configuration"
            )
        if existing.get("status") != "ready":
            raise WanError(
                f"WAN bridge {name} has unfinished provisioning; clean it up before retrying"
            )
        workspaces = existing.get("workspaces")
        if not isinstance(workspaces, list) or any(
            not isinstance(item, str) for item in workspaces
        ):
            raise WanError(
                f"WAN registry entry for {name} has invalid workspace claims"
            )
        if workspace not in workspaces:
            workspaces.append(workspace)
            workspaces.sort()
            save_registry(locked, registry)
        return False, existing


def complete_provisioning(
    state: StateStore, name: str, metadata: Mapping[str, Any]
) -> None:
    with state.transaction() as locked:
        registry = load_registry(locked)
        bridges = registry["bridges"]
        assert isinstance(bridges, dict)
        entry = bridges.get(name)
        if not isinstance(entry, dict) or entry.get("status") != "provisioning":
            raise WanError(f"WAN bridge {name} is not awaiting provisioning")
        entry["metadata"] = dict(metadata)
        entry["status"] = "ready"
        save_registry(locked, registry)


def record_provision_step(state: StateStore, name: str, step: str) -> None:
    with state.transaction() as locked:
        registry = load_registry(locked)
        bridges = registry["bridges"]
        assert isinstance(bridges, dict)
        entry = bridges.get(name)
        if not isinstance(entry, dict) or entry.get("status") != "provisioning":
            raise WanError(f"WAN bridge {name} is not awaiting provisioning")
        journal = entry.get("journal")
        if not isinstance(journal, list) or any(
            not isinstance(item, str) for item in journal
        ):
            raise WanError(f"WAN bridge {name} has an invalid provisioning journal")
        if step not in journal:
            journal.append(step)
            save_registry(locked, registry)


def begin_rollback(state: StateStore, name: str) -> dict[str, Any] | None:
    with state.transaction() as locked:
        registry = load_registry(locked)
        bridges = registry["bridges"]
        assert isinstance(bridges, dict)
        entry = bridges.get(name)
        if entry is None or (
            isinstance(entry, dict) and entry.get("status") == "ready"
        ):
            return None
        if not isinstance(entry, dict) or entry.get("status") not in {
            "provisioning",
            "rolling-back",
        }:
            raise WanError(f"WAN bridge {name} is not awaiting rollback")
        configuration = entry.get("configuration")
        journal = entry.get("journal")
        if not isinstance(configuration, dict) or not isinstance(journal, list):
            raise WanError(f"WAN bridge {name} has invalid rollback metadata")
        entry["status"] = "rolling-back"
        save_registry(locked, registry)
        return {
            **configuration,
            "created": "bridge-created" in journal,
            "gateway_added": "gateway-added" in journal,
        }


def complete_rollback(state: StateStore, name: str) -> bool:
    with state.transaction() as locked:
        registry = load_registry(locked)
        bridges = registry["bridges"]
        assert isinstance(bridges, dict)
        bridges.pop(name, None)
        empty = not bridges
        save_registry(locked, registry)
        return empty


def release_bridge(
    state: StateStore,
    *,
    workspace: str,
    name: str,
) -> dict[str, Any] | None:
    """Remove one workspace claim; return metadata only for the final claimant."""
    with state.transaction() as locked:
        registry = load_registry(locked)
        bridges = registry["bridges"]
        assert isinstance(bridges, dict)
        entry = bridges.get(name)
        if entry is None:
            return None
        if not isinstance(entry, dict):
            raise WanError(f"WAN registry entry for {name} is invalid")
        workspaces = entry.get("workspaces")
        if not isinstance(workspaces, list):
            raise WanError(
                f"WAN registry entry for {name} has invalid workspace claims"
            )
        if workspace in workspaces:
            workspaces.remove(workspace)
        if workspaces:
            save_registry(locked, registry)
            return None

        metadata = entry.get("metadata")
        if not isinstance(metadata, dict):
            raise WanError(
                f"WAN bridge {name} has no recoverable provisioning metadata"
            )
        entry["status"] = "tearing-down"
        save_registry(locked, registry)
        return metadata


def complete_release(state: StateStore, name: str) -> bool:
    """Forget one successfully removed bridge and return whether the registry is empty."""
    with state.transaction() as locked:
        registry = load_registry(locked)
        bridges = registry["bridges"]
        assert isinstance(bridges, dict)
        bridges.pop(name, None)
        empty = not bridges
        save_registry(locked, registry)
        return empty


def bridge_metadata_for_workspace(state: StateStore, names: list[str]) -> None:
    state.write_text("dhcp-wan.json", json.dumps(sorted(set(names))) + "\n")


def workspace_bridge_names(state: StateStore) -> list[str]:
    if not state.exists("dhcp-wan.json"):
        return []
    try:
        value: Any = json.loads(state.read_text("dhcp-wan.json"))
    except json.JSONDecodeError as error:
        raise WanError(f"dhcp-wan.json is not valid JSON: {error}") from error
    if not isinstance(value, list) or any(not isinstance(name, str) for name in value):
        raise WanError("dhcp-wan.json has an invalid schema")
    return sorted(set(value))
