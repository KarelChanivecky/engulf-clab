from __future__ import annotations

import ipaddress
import unittest
from unittest.mock import Mock, patch

from engulf_clab_sticky_ip.errors import ProbeUnavailableError
from engulf_clab_sticky_ip.host import probe_candidate
from engulf_clab_sticky_ip.probe_linux import LinuxUDPTraceStrategy
from engulf_clab_sticky_ip.probe_windows import WindowsTraceStrategy
from engulf_clab_sticky_ip.probes import (
    TraceStrategy,
    UnsupportedTraceStrategy,
    select_trace_strategy,
)


class ProbeStrategyTest(unittest.TestCase):
    def test_linux_selects_udp_strategy(self) -> None:
        with patch("engulf_clab_sticky_ip.probes.sys.platform", "linux"):
            self.assertIsInstance(select_trace_strategy(), LinuxUDPTraceStrategy)

    def test_windows_stub_is_unavailable_without_importing_linux(self) -> None:
        with (
            patch("engulf_clab_sticky_ip.probes.sys.platform", "win32"),
            patch.dict("sys.modules", {"engulf_clab_sticky_ip.probe_linux": None}),
        ):
            strategy = select_trace_strategy()
            self.assertIsInstance(strategy, WindowsTraceStrategy)
            with self.assertRaisesRegex(ProbeUnavailableError, "Windows"):
                strategy.trace(ipaddress.ip_address("10.20.0.2"), 0.1)

    def test_unknown_platform_strategy_is_unavailable(self) -> None:
        with patch("engulf_clab_sticky_ip.probes.sys.platform", "darwin"):
            strategy = select_trace_strategy()
            self.assertIsInstance(strategy, UnsupportedTraceStrategy)
            with self.assertRaisesRegex(ProbeUnavailableError, "darwin"):
                strategy.trace(ipaddress.ip_address("10.20.0.2"), 0.1)

    def test_candidate_probe_accepts_an_injected_strategy(self) -> None:
        strategy = Mock(spec=TraceStrategy)
        strategy.trace.return_value = (ipaddress.ip_address("10.20.0.1"),)
        with patch("engulf_clab_sticky_ip.host.select_trace_strategy") as select:
            self.assertTrue(
                probe_candidate(ipaddress.ip_network("10.20.0.0/24"), strategy=strategy)
            )
            select.assert_not_called()
        self.assertEqual(strategy.trace.call_count, 2)

    def test_candidate_probe_propagates_windows_unavailable_exception(self) -> None:
        with self.assertRaises(ProbeUnavailableError):
            probe_candidate(ipaddress.ip_network("10.20.0.0/24"), strategy=WindowsTraceStrategy())
