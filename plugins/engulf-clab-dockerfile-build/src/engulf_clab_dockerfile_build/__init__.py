"""Dockerfile image-build plugin for engulf-clab."""

from .plugin import DockerfilePlugin

plugin = DockerfilePlugin()

__all__ = ["DockerfilePlugin", "plugin"]
