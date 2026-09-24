from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from threading import RLock
from types import MappingProxyType

from engulf_api import InvocationAPI

VRNETLAB_BUILD_CONTEXT = "org.engulf.clab.vrnetlab-build.sources"
DEFAULT_NODE_NAME = "default"


class DuplicateImageSourceError(ValueError):
    """Raised when a source key is written twice without explicit override."""


class VrnetlabBuildContext:
    """Invocation-scoped source declarations collected from active providers."""

    def __init__(self) -> None:
        self._sources: dict[str, Path] = {}
        self._max_workers: int | None = None
        self._lock = RLock()

    def _set_source(
        self,
        path: Path,
        node_name: str = DEFAULT_NODE_NAME,
        *,
        override: bool = False,
    ) -> None:
        """Publish a source, replacing an existing node only when requested."""
        _validate_node_name(node_name)
        if not isinstance(path, Path) or not path.is_absolute():
            raise ValueError("vrnetlab source path must be an absolute Path")
        if type(override) is not bool:
            raise TypeError("override must be a bool")
        with self._lock:
            if node_name in self._sources and not override:
                raise DuplicateImageSourceError(
                    f"vrnetlab source for node {node_name!r} was already set"
                )
            self._sources[node_name] = path

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
        override: bool = False,
    ) -> None:
        """Publish a path; optionally replace an earlier source for this node."""
        self._context._set_source(path, node_name, override=override)

    def unprovisioned_nodes(self, node_names: Iterable[str]) -> tuple[str, ...]:
        """Return candidate nodes with no exact-node or default source."""
        return self._context._unprovisioned_nodes(node_names)

    def source_for(self, node_name: str) -> Path | None:
        """Return the exact-node source or the default source if present."""
        return self._context._source_for(node_name)

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
        raise RuntimeError(f"invalid vrnetlab build context {VRNETLAB_BUILD_CONTEXT}")
    return value


def _validate_node_name(node_name: str) -> None:
    if not isinstance(node_name, str) or not node_name.strip() or "\0" in node_name:
        raise ValueError("vrnetlab source node name must be a nonempty string")
