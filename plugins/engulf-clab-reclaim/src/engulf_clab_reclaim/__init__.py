"""Docker-only lab storage reclamation for eclab."""

from .plugin import ReclaimPlugin

plugin = ReclaimPlugin()

__all__ = ["ReclaimPlugin", "plugin"]
