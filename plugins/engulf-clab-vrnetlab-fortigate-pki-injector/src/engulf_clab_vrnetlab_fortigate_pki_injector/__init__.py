"""FortiGate vrnetlab PKI projection injector."""

from .plugin import PLUGIN_SCHEMA, FortigatePkiInjector, InjectorError

plugin = FortigatePkiInjector()

__all__ = ["PLUGIN_SCHEMA", "FortigatePkiInjector", "InjectorError", "plugin"]
