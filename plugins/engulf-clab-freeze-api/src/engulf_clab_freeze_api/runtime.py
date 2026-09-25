"""Edition-owned runtime behavior for format 3 freeze archives."""

from __future__ import annotations

import importlib.metadata
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .contract import FreezeError

RUNTIME_PROVIDER_GROUP = "engulf_clab.freeze.runtime.v1"


@runtime_checkable
class RuntimeProvider(Protocol):
    edition: str

    def capture(self, environment: Mapping[str, str], user_state: Path | None) -> Mapping[str, Any]: ...

    def prepare_archive(self, root: Path, mode: str, tools: Mapping[str, Any], environment: Mapping[str, str], user_state: Path | None, warnings: list[str]) -> None: ...

    def check_recipient(self, tools: Mapping[str, Any], environment: Mapping[str, str], user_state: Path | None) -> list[str]: ...

    def prepare_recipient(self, root: Path, mode: str, tools: Mapping[str, Any], environment: Mapping[str, str], user_state: Path | None, notes: list[str]) -> None: ...

    def launcher(self, topology: str, mode: str, tools: Mapping[str, Any]) -> str: ...


def discover_runtime_providers() -> dict[str, RuntimeProvider]:
    """Load providers by edition; an archive must never silently change edition."""
    found: dict[str, RuntimeProvider] = {}
    for entry in sorted(importlib.metadata.entry_points(group=RUNTIME_PROVIDER_GROUP), key=lambda item: item.name):
        candidate = entry.load()
        provider = candidate() if isinstance(candidate, type) else candidate
        if not isinstance(provider, RuntimeProvider) or provider.edition != entry.name:
            raise FreezeError(f"runtime provider {entry.name!r} has an invalid contract or edition")
        if entry.name in found:
            raise FreezeError(f"duplicate runtime provider for {entry.name!r}")
        found[entry.name] = provider
    return found


def runtime_provider(edition: str) -> RuntimeProvider:
    provider = discover_runtime_providers().get(edition)
    if provider is None:
        raise FreezeError(f"no freeze runtime provider is installed for edition {edition!r}")
    return provider
