from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from types import MappingProxyType

from engulf_api import InvocationAPI, validate_global_identifier

VRNETLAB_BUILD_CONTEXT = "org.engulf.clab.vrnetlab-build.sources"
VRNETLAB_SOURCE_PROVENANCE_CONTEXT = "org.engulf.clab.vrnetlab-build.source-provenance"
DEFAULT_NODE_NAME = "default"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class VrnetlabSourceProvenance:
    """Source attribution and an optional diagnostic path for one node."""

    node_name: str
    builder_type: str
    source_provider_id: str | None
    source_sha256: str
    source_path: str | None = None

    def __post_init__(self) -> None:
        _validate_node_name(self.node_name)
        if (
            not isinstance(self.builder_type, str)
            or not self.builder_type.strip()
            or "\0" in self.builder_type
        ):
            raise ValueError("vrnetlab provenance builder type must be nonempty and NUL-free")
        if self.source_provider_id is not None:
            validate_global_identifier(
                self.source_provider_id, label="vrnetlab source provider ID"
            )
        if not isinstance(self.source_sha256, str) or not _SHA256.fullmatch(
            self.source_sha256
        ):
            raise ValueError("vrnetlab source provenance must contain a lowercase SHA-256")
        if self.source_path is not None and (
            not isinstance(self.source_path, str)
            or not Path(self.source_path).is_absolute()
            or "\0" in self.source_path
        ):
            raise ValueError("vrnetlab source provenance path must be absolute and NUL-free")


@dataclass(frozen=True, slots=True)
class VrnetlabSourceProvenanceSnapshot:
    """Source-provider records for every vrnetlab node in a deployment."""

    sources: tuple[VrnetlabSourceProvenance, ...] = ()

    def __post_init__(self) -> None:
        if type(self.sources) is not tuple or any(
            not isinstance(item, VrnetlabSourceProvenance) for item in self.sources
        ):
            raise TypeError(
                "vrnetlab sources must be a tuple of VrnetlabSourceProvenance values"
            )
        keys = tuple(item.node_name for item in self.sources)
        if len(set(keys)) != len(keys):
            raise ValueError("vrnetlab source provenance must have one record per node")

    def source_for(self, node_name: str) -> VrnetlabSourceProvenance | None:
        _validate_node_name(node_name)
        for item in self.sources:
            if item.node_name == node_name:
                return item
        return None


class DuplicateImageSourceError(ValueError):
    """Raised when a source key is written twice without explicit override."""


class VrnetlabBuildContext:
    """Invocation-scoped source declarations collected from active providers."""

    def __init__(self) -> None:
        self._sources: dict[str, Path] = {}
        self._source_provider_ids: dict[str, str] = {}
        self._persist_source_paths: dict[str, bool] = {}
        self._max_workers: int | None = None
        self._lock = RLock()

    def _set_source(
        self,
        path: Path,
        node_name: str = DEFAULT_NODE_NAME,
        *,
        source_provider_id: str | None = None,
        persist_source_path: bool = False,
        override: bool = False,
    ) -> None:
        """Publish a source, replacing an existing node only when requested."""
        _validate_node_name(node_name)
        if not isinstance(path, Path) or not path.is_absolute():
            raise ValueError("vrnetlab source path must be an absolute Path")
        if source_provider_id is not None:
            validate_global_identifier(source_provider_id, label="source_provider_id")
        if type(persist_source_path) is not bool:
            raise TypeError("persist_source_path must be a bool")
        if type(override) is not bool:
            raise TypeError("override must be a bool")
        with self._lock:
            if node_name in self._sources and not override:
                raise DuplicateImageSourceError(
                    f"vrnetlab source for node {node_name!r} was already set"
                )
            self._sources[node_name] = path
            if source_provider_id is None:
                self._source_provider_ids.pop(node_name, None)
            else:
                self._source_provider_ids[node_name] = source_provider_id
            self._persist_source_paths[node_name] = persist_source_path

    def _unprovisioned_nodes(self, node_names: Iterable[str]) -> tuple[str, ...]:
        """Return candidates with neither an exact-node nor default source."""
        if isinstance(node_names, (str, bytes)):
            raise TypeError("node_names must be an iterable of node names")
        candidates = tuple(node_names)
        for node_name in candidates:
            _validate_node_name(node_name)

        with self._lock:
            has_default = DEFAULT_NODE_NAME in self._sources
            return tuple(
                node_name
                for node_name in candidates
                if node_name not in self._sources and not has_default
            )

    def _source_for(self, node_name: str) -> Path | None:
        with self._lock:
            return self._sources.get(node_name, self._sources.get(DEFAULT_NODE_NAME))

    def _uses_default_source(self, node_name: str) -> bool:
        _validate_node_name(node_name)
        with self._lock:
            return (
                DEFAULT_NODE_NAME in self._sources
                and (node_name not in self._sources or node_name == DEFAULT_NODE_NAME)
            )

    def _source_provenance_for(self, node_name: str) -> str | None:
        with self._lock:
            if node_name in self._sources:
                return self._source_provider_ids.get(node_name)
            return self._source_provider_ids.get(DEFAULT_NODE_NAME)

    def _persist_source_path_for(self, node_name: str) -> bool:
        with self._lock:
            source_key = node_name if node_name in self._sources else DEFAULT_NODE_NAME
            return self._persist_source_paths.get(source_key, False)

    def sources(self) -> Mapping[str, Path]:
        with self._lock:
            return MappingProxyType(dict(self._sources))

    def _set_max_workers(self, value: int) -> None:
        if type(value) is not int or value < 1:
            raise ValueError("vrnetlab build jobs must be a positive integer")
        with self._lock:
            if self._max_workers is not None and self._max_workers != value:
                raise ValueError(
                    "vrnetlab providers supplied conflicting image build job limits"
                )
            self._max_workers = value

    @property
    def max_workers(self) -> int | None:
        with self._lock:
            return self._max_workers


class VrnetlabBuildAPI:
    """Provider and builder operations bound to one invocation context."""

    def __init__(self, context: VrnetlabBuildContext) -> None:
        if not isinstance(context, VrnetlabBuildContext):
            raise TypeError("context must be a VrnetlabBuildContext")
        self._context = context

    def set_image_source(
        self,
        path: Path,
        node_name: str = DEFAULT_NODE_NAME,
        *,
        source_provider_id: str | None = None,
        persist_source_path: bool = False,
        override: bool = False,
    ) -> None:
        """Publish a path and attribution, optionally retaining its path for diagnostics."""
        self._context._set_source(
            path,
            node_name,
            source_provider_id=source_provider_id,
            persist_source_path=persist_source_path,
            override=override,
        )

    def unprovisioned_nodes(self, node_names: Iterable[str]) -> tuple[str, ...]:
        """Return candidate nodes with no exact-node or default source."""
        return self._context._unprovisioned_nodes(node_names)

    def source_for(self, node_name: str) -> Path | None:
        """Return the exact-node source or the default source if present."""
        return self._context._source_for(node_name)

    def source_provenance_for(self, node_name: str) -> str | None:
        """Return the provider ID for the exact or default source declaration."""
        _validate_node_name(node_name)
        return self._context._source_provenance_for(node_name)

    def persists_source_path_for(self, node_name: str) -> bool:
        """Return whether provenance for the exact or default source includes its path."""
        _validate_node_name(node_name)
        return self._context._persist_source_path_for(node_name)

    def uses_default_source(self, node_name: str) -> bool:
        """Return whether source lookup for a node falls back to `default`."""
        return self._context._uses_default_source(node_name)

    def sources(self) -> Mapping[str, Path]:
        """Return an immutable snapshot of source declarations."""
        return self._context.sources()

    def set_build_jobs(self, value: int) -> None:
        """Publish the validated concurrency setting for the shared builder."""
        self._context._set_max_workers(value)

    @property
    def max_workers(self) -> int | None:
        """Return the configured worker limit, if a provider supplied one."""
        return self._context.max_workers


def vrnetlab_source_provenance(
    api: InvocationAPI,
) -> VrnetlabSourceProvenanceSnapshot:
    value = api.get_context(
        VRNETLAB_SOURCE_PROVENANCE_CONTEXT, VrnetlabSourceProvenanceSnapshot()
    )
    if not isinstance(value, VrnetlabSourceProvenanceSnapshot):
        raise TypeError("invalid vrnetlab source provenance context")
    return value


def publish_vrnetlab_source_provenance(
    api: InvocationAPI,
    snapshot: VrnetlabSourceProvenanceSnapshot,
) -> None:
    if not isinstance(snapshot, VrnetlabSourceProvenanceSnapshot):
        raise TypeError("snapshot must be a VrnetlabSourceProvenanceSnapshot")
    api.set_context(
        VRNETLAB_SOURCE_PROVENANCE_CONTEXT,
        snapshot,
        allow_unused=True,
    )


def get_build_context(
    api: InvocationAPI,
    *,
    create: bool = False,
) -> VrnetlabBuildContext | None:
    """Read or initialize the context used to construct ``VrnetlabBuildAPI``."""
    value = api.get_context(VRNETLAB_BUILD_CONTEXT)
    if value is None:
        if not create:
            return None
        value = VrnetlabBuildContext()
        api.set_context(VRNETLAB_BUILD_CONTEXT, value)
    if not isinstance(value, VrnetlabBuildContext):
        raise TypeError(f"invalid vrnetlab build context {VRNETLAB_BUILD_CONTEXT}")
    return value


def _validate_node_name(node_name: str) -> None:
    if not isinstance(node_name, str) or not node_name.strip() or "\0" in node_name:
        raise ValueError("vrnetlab source node name must be a nonempty string")
