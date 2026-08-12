"""Post-deploy Containerlab node health gates for engulf-clab."""

from .plugin import HealthGatesPlugin

plugin = HealthGatesPlugin()

__all__ = ["HealthGatesPlugin", "plugin"]
