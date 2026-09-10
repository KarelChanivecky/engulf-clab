"""Resource-consumption reporting for eclab."""

from .plugin import ConsumptionPlugin

plugin = ConsumptionPlugin()

__all__ = ["ConsumptionPlugin", "plugin"]
