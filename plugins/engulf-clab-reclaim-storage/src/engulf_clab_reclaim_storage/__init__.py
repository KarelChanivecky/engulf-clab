"""Docker-only lab storage reclamation for eclab."""

from .plugin import ReclaimStoragePlugin

plugin = ReclaimStoragePlugin()

__all__ = ["ReclaimStoragePlugin", "plugin"]
