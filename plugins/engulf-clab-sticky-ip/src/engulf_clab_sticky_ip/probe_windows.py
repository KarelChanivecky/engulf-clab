from __future__ import annotations

from .allocation import Address
from .errors import ProbeUnavailableError


class WindowsTraceStrategy:
    """Placeholder for a future Windows network probe implementation."""

    def trace(self, target: Address, timeout: float) -> tuple[Address, ...]:
        raise ProbeUnavailableError("network probes are not implemented for Windows")
