"""Public API for the shared engulf-clab lab registry."""

from .contract import (
    LAB_REGISTRY_COMMIT_CONTEXT,
    LAB_REGISTRY_CONTEXT,
    LAB_REGISTRY_PLUGIN_ID,
    LabRecord,
    LabRegistry,
    LabRegistryError,
    RegistryCommit,
    Workspace,
    lab_registry,
)

__all__ = [
    "LAB_REGISTRY_COMMIT_CONTEXT",
    "LAB_REGISTRY_CONTEXT",
    "LAB_REGISTRY_PLUGIN_ID",
    "LabRecord",
    "LabRegistry",
    "LabRegistryError",
    "RegistryCommit",
    "Workspace",
    "lab_registry",
]
