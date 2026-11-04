"""Host-operated tcpdump capture for Containerlab node links."""

from .plugin import SniffPlugin

plugin = SniffPlugin()

__all__ = ["SniffPlugin", "plugin"]
