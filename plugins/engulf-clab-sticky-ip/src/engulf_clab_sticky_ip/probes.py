from __future__ import annotations

import sys
from typing import Protocol

from .allocation import Address
from .errors import ProbeUnavailableError


class TraceStrategy(Protocol):
    def trace(self, target: Address, timeout: float) -> tuple[Address, ...]:
        """Return responding hops, or raise ProbeUnavailableError if unsupported."""
        ...


class UnsupportedTraceStrategy:
    def __init__(self, platform: str) -> None:
        self._platform = platform

    def trace(self, target: Address, timeout: float) -> tuple[Address, ...]:
        raise ProbeUnavailableError(f"network probes are not implemented for {self._platform}")


def select_trace_strategy() -> TraceStrategy:
    # Import only the selected implementation: Windows lacks Linux socket and
    # polling APIs and must still be able to import the plugin.
    if sys.platform == "linux":
        from .probe_linux import LinuxUDPTraceStrategy

        return LinuxUDPTraceStrategy()
    if sys.platform == "win32":
        from .probe_windows import WindowsTraceStrategy

        return WindowsTraceStrategy()
    return UnsupportedTraceStrategy(sys.platform)
