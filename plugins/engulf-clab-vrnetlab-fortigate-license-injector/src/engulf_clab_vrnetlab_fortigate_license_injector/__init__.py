from .plugin import FortigateLicenseInjector, InjectorError

plugin = FortigateLicenseInjector()

__all__ = ["FortigateLicenseInjector", "InjectorError", "plugin"]
