"""Shared persistent lab inventory for engulf-clab."""

from .plugin import LabRegistryPlugin

plugin = LabRegistryPlugin()

__all__ = ["LabRegistryPlugin", "plugin"]
