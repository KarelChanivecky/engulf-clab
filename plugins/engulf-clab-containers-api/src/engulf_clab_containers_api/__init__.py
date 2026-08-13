"""Public declarative API for engulf-clab container collections."""

from .contract import (
    CONTAINER_COLLECTION_CONTEXT,
    CONTAINER_MANAGER_PLUGIN_ID,
    ContainerBuildRecipe,
    ContainerCollectionPlugin,
    ContainerDefinition,
    ContainerNodeRequirements,
    RegisteredContainerCollection,
    image_namespace,
)

__all__ = [
    "CONTAINER_COLLECTION_CONTEXT",
    "CONTAINER_MANAGER_PLUGIN_ID",
    "ContainerBuildRecipe",
    "ContainerCollectionPlugin",
    "ContainerDefinition",
    "ContainerNodeRequirements",
    "RegisteredContainerCollection",
    "image_namespace",
]
