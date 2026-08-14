"""Core eclab container collection."""

from .plugin import HOST_CONNECTOR, LDAP_389DS, PROXY_NODE, UBUNTU_FIREFOX_GUI, plugin

__all__ = [
    "HOST_CONNECTOR",
    "LDAP_389DS",
    "PROXY_NODE",
    "UBUNTU_FIREFOX_GUI",
    "plugin",
]
