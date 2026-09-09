"""PKI-enabled eclab base container collection."""

from .plugin import DEBIAN, FEDORA, image_plugin, plugin

__all__ = [
    "DEBIAN",
    "FEDORA",
    "image_plugin",
    "plugin",
]
