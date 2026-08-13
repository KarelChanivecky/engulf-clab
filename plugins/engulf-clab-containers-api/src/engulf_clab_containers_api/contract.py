from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from engulf_api import (
    BeforeGoalAPI,
    DependencyPosition,
    GoalResult,
    Invocation,
    PluginDependency,
)
from engulf_executable_wrapper_api import ExecutableWrapperPlugin

CONTAINER_COLLECTION_CONTEXT = "engulf_clab.containers.collections"
CONTAINER_MANAGER_PLUGIN_ID = "engulf_clab.containers"
_NAME = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_PLUGIN_ID = re.compile(r"^[a-z0-9]+(?:[._][a-z0-9]+)+$")


def _strings(values: tuple[str, ...], *, label: str) -> tuple[str, ...]:
    if type(values) is not tuple or any(
        not isinstance(value, str) or not value for value in values
    ):
        raise TypeError(f"{label} must be a tuple of nonempty strings")
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must not contain duplicates")
    return values


def _string_mapping(values: Mapping[str, str | int], *, label: str) -> Mapping[str, str | int]:
    try:
        copied = dict(values)
    except (TypeError, ValueError) as error:
        raise TypeError(f"{label} must be a mapping") from error
    if any(not isinstance(key, str) or not key for key in copied):
        raise TypeError(f"{label} keys must be nonempty strings")
    if any(
        not isinstance(value, (str, int)) or isinstance(value, bool) for value in copied.values()
    ):
        raise TypeError(f"{label} values must be strings or integers")
    return MappingProxyType(copied)


@dataclass(frozen=True, slots=True)
class ContainerBuildRecipe:
    dockerfile: Path
    context: Path

    def __post_init__(self) -> None:
        if not isinstance(self.dockerfile, Path) or not self.dockerfile.is_absolute():
            raise ValueError("container Dockerfile path must be absolute")
        if not isinstance(self.context, Path) or not self.context.is_absolute():
            raise ValueError("container build context path must be absolute")


@dataclass(frozen=True, slots=True)
class ContainerNodeRequirements:
    kind: str = "linux"
    cap_add: tuple[str, ...] = ()
    sysctls: Mapping[str, str | int] = field(default_factory=dict)
    environment: Mapping[str, str | int] = field(default_factory=dict)
    requires_management: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or not self.kind:
            raise TypeError("container kind must be a nonempty string")
        object.__setattr__(self, "cap_add", _strings(self.cap_add, label="cap_add"))
        object.__setattr__(self, "sysctls", _string_mapping(self.sysctls, label="sysctls"))
        object.__setattr__(
            self, "environment", _string_mapping(self.environment, label="environment")
        )
        if type(self.requires_management) is not bool:
            raise TypeError("requires_management must be a boolean")


@dataclass(frozen=True, slots=True)
class ContainerDefinition:
    name: str
    summary: str
    build: ContainerBuildRecipe
    node: ContainerNodeRequirements = field(default_factory=ContainerNodeRequirements)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or _NAME.fullmatch(self.name) is None:
            raise ValueError("container name must be a lowercase Docker-safe name")
        if not isinstance(self.summary, str) or not self.summary.strip():
            raise ValueError("container summary must be nonempty")
        if not isinstance(self.build, ContainerBuildRecipe):
            raise TypeError("container build must be a ContainerBuildRecipe")
        if not isinstance(self.node, ContainerNodeRequirements):
            raise TypeError("container node must be ContainerNodeRequirements")


@dataclass(frozen=True, slots=True)
class RegisteredContainerCollection:
    plugin_id: str
    containers: tuple[ContainerDefinition, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.plugin_id, str) or _PLUGIN_ID.fullmatch(self.plugin_id) is None:
            raise ValueError("collection plugin ID must be a lowercase dot-qualified identifier")
        if type(self.containers) is not tuple or any(
            not isinstance(item, ContainerDefinition) for item in self.containers
        ):
            raise TypeError("collection containers must be a tuple of ContainerDefinition values")


def image_namespace(plugin_id: str) -> str:
    return plugin_id.replace("_", "-")


class ContainerCollectionPlugin(ExecutableWrapperPlugin):
    """Declarative Engulf plugin that contributes packaged container recipes."""

    context_reads = frozenset({CONTAINER_COLLECTION_CONTEXT})
    context_writes = frozenset({CONTAINER_COLLECTION_CONTEXT})
    plugin_dependencies = (
        PluginDependency(
            CONTAINER_MANAGER_PLUGIN_ID,
            preprocess=DependencyPosition.AFTER,
            postprocess=None,
        ),
    )

    def __init__(self, plugin_id: str, containers: tuple[ContainerDefinition, ...]) -> None:
        collection = RegisteredContainerCollection(plugin_id, containers)
        self.plugin_id = collection.plugin_id
        self.containers = collection.containers

    def before_goal(self, invocation: Invocation, api: BeforeGoalAPI) -> GoalResult[object] | None:
        del invocation
        current = api.get_context(CONTAINER_COLLECTION_CONTEXT, ())
        if type(current) is not tuple or any(
            not isinstance(item, RegisteredContainerCollection) for item in current
        ):
            raise RuntimeError("invalid container collection registry")
        api.set_context(
            CONTAINER_COLLECTION_CONTEXT,
            (*current, RegisteredContainerCollection(self.plugin_id, self.containers)),
        )
        return None
