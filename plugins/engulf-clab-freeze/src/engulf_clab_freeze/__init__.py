"""Portable frozen-lab archive support."""

from .plugin import FreezePlugin

plugin = FreezePlugin()

__all__ = ["FreezePlugin", "plugin"]
