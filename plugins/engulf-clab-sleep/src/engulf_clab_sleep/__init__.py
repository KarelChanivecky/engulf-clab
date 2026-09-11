"""Docker-only lab storage reclamation for eclab."""

from .plugin import SleepPlugin

plugin = SleepPlugin()

__all__ = ["SleepPlugin", "plugin"]
