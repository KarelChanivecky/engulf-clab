"""Containerlab executable provisioning plugin."""

from .contract import ENSURE_CONTAINERLAB_PLUGIN_ID
from .plugin import EnsureContainerlabPlugin

plugin = EnsureContainerlabPlugin()

__all__ = ["ENSURE_CONTAINERLAB_PLUGIN_ID", "EnsureContainerlabPlugin", "plugin"]
