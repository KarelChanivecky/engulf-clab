from __future__ import annotations

import errno
import ipaddress
import select
import socket
import struct
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import Mock, patch

from engulf_clab_sticky_ip.errors import HostCheckError, ProbeUnavailableError
from engulf_clab_sticky_ip.probe_linux import LinuxUDPTraceStrategy, _trace_reply


class LinuxTraceTest(unittest.TestCase):
    def test_missing_error_queue_support_is_unavailable(self) -> None:
        for number in (errno.ENOPROTOOPT, errno.EOPNOTSUPP, errno.ENOSYS):
            with self.subTest(number=number), self.trace_socket() as (probe, _):
                probe.setsockopt.side_effect = OSError(number, "not supported")
                with self.assertRaises(ProbeUnavailableError):
                    LinuxUDPTraceStrategy().trace(ipaddress.ip_address("10.10.0.2"), 0.05)

    def test_unsupported_address_family_is_unavailable(self) -> None:
        with (
            patch(
                "engulf_clab_sticky_ip.probe_linux.socket.socket",
                side_effect=OSError(errno.EAFNOSUPPORT, "not supported"),
            ),
            self.assertRaises(ProbeUnavailableError),
        ):
            LinuxUDPTraceStrategy().trace(ipaddress.ip_address("fd00::2"), 0.05)

    @contextmanager
    def trace_socket(self) -> Iterator[tuple[Mock, Mock]]:
        with (
            patch("engulf_clab_sticky_ip.probe_linux.socket.socket") as factory,
            patch("engulf_clab_sticky_ip.probe_linux.select.poll") as poll,
            patch("engulf_clab_sticky_ip.probe_linux.time.monotonic", return_value=0.0),
        ):
            probe = factory.return_value.__enter__.return_value
            poller = poll.return_value
            yield probe, poller
            factory.return_value.__exit__.assert_called_once()

    @staticmethod
    def error_message(address: str, kind: int) -> tuple[int, int, bytes]:
        offender = ipaddress.ip_address(address)
        ipv4 = offender.version == 4
        header = struct.pack("=IBBBBII", errno.EHOSTUNREACH, 2 if ipv4 else 3, kind, 0, 0, 0, 0)
        sockaddr = struct.pack(
            "=H2x4s8x" if ipv4 else "=H6x16s4x",
            socket.AF_INET if ipv4 else socket.AF_INET6,
            offender.packed,
        )
        return (
            socket.IPPROTO_IP if ipv4 else socket.IPPROTO_IPV6,
            11 if ipv4 else 25,
            header + sockaddr,
        )

    def test_trace_silence_is_bounded_and_closes_the_socket(self) -> None:
        with self.trace_socket() as (probe, poller):
            poller.poll.return_value = []

            self.assertEqual(
                LinuxUDPTraceStrategy().trace(ipaddress.ip_address("10.10.0.2"), 0.05), ()
            )

            probe.setblocking.assert_called_once_with(False)
            probe.connect.assert_called_once_with(("10.10.0.2", 33434))
            probe.send.assert_called_once()
            poller.poll.assert_called_once_with(50)

    def test_trace_decodes_router_and_destination_for_both_families(self) -> None:
        for router, destination, exceeded, unreachable, level, option, hop_option in (
            ("192.168.1.1", "10.10.0.2", 11, 3, socket.IPPROTO_IP, 11, socket.IP_TTL),
            ("fe80::1", "fd00::2", 3, 1, socket.IPPROTO_IPV6, 25, socket.IPV6_UNICAST_HOPS),
        ):
            with self.subTest(destination=destination), self.trace_socket() as (probe, poller):
                poller.poll.return_value = [(3, select.POLLERR)]
                # recvmsg's address is the quoted destination, not the router.
                probe.recvmsg.side_effect = (
                    (b"sticky-ip", [self.error_message(router, exceeded)], 0, (destination, 33434)),
                    (
                        b"sticky-ip",
                        [self.error_message(destination, unreachable)],
                        0,
                        (destination, 33434),
                    ),
                )

                self.assertEqual(
                    LinuxUDPTraceStrategy().trace(ipaddress.ip_address(destination), 0.05),
                    (ipaddress.ip_address(router), ipaddress.ip_address(destination)),
                )

                probe.setsockopt.assert_any_call(level, option, 1)
                probe.setsockopt.assert_any_call(level, hop_option, 1)
                probe.setsockopt.assert_any_call(level, hop_option, 2)
                self.assertEqual(probe.send.call_count, 2)

    def test_trace_stops_after_eight_hops(self) -> None:
        with self.trace_socket() as (probe, poller):
            poller.poll.return_value = [(3, select.POLLERR)]
            probe.recvmsg.return_value = (b"", [self.error_message("192.168.1.1", 11)], 0, ())

            self.assertEqual(
                len(LinuxUDPTraceStrategy().trace(ipaddress.ip_address("10.10.0.2"), 0.05)), 8
            )

            self.assertEqual(probe.send.call_count, 8)
            probe.setsockopt.assert_any_call(socket.IPPROTO_IP, socket.IP_TTL, 8)

    def test_trace_shares_one_deadline_across_hops(self) -> None:
        with self.trace_socket() as (probe, poller):
            poller.poll.return_value = [(3, select.POLLERR)]
            probe.recvmsg.return_value = (b"", [self.error_message("192.168.1.1", 11)], 0, ())
            with patch(
                "engulf_clab_sticky_ip.probe_linux.time.monotonic",
                side_effect=(0.0, 0.0, 0.01, 0.06),
            ):
                self.assertEqual(
                    LinuxUDPTraceStrategy().trace(ipaddress.ip_address("10.10.0.2"), 0.05),
                    (ipaddress.ip_address("192.168.1.1"),),
                )

            probe.send.assert_called_once()
            poller.poll.assert_called_once_with(40)

    def test_trace_accepts_normal_udp_reply(self) -> None:
        with self.trace_socket() as (probe, poller):
            poller.poll.return_value = [(3, select.POLLIN)]
            probe.recv.return_value = b"reply"
            target = ipaddress.ip_address("10.10.0.2")

            self.assertEqual(LinuxUDPTraceStrategy().trace(target, 0.05), (target,))

    def test_trace_retries_empty_error_queue_within_deadline(self) -> None:
        with self.trace_socket() as (probe, poller):
            poller.poll.return_value = [(3, select.POLLERR)]
            probe.recvmsg.side_effect = (
                BlockingIOError(errno.EAGAIN, "try again"),
                (b"", [self.error_message("10.10.0.2", 3)], 0, ()),
            )

            self.assertEqual(
                LinuxUDPTraceStrategy().trace(ipaddress.ip_address("10.10.0.2"), 0.05),
                (ipaddress.ip_address("10.10.0.2"),),
            )

            self.assertEqual(probe.recvmsg.call_count, 2)

    def test_trace_unreachable_route_is_not_a_response(self) -> None:
        for operation in ("connect", "send"):
            for number in (errno.ENETUNREACH, errno.EHOSTUNREACH):
                with (
                    self.subTest(operation=operation, number=number),
                    self.trace_socket() as (probe, _),
                ):
                    getattr(probe, operation).side_effect = OSError(number, "unreachable")

                    self.assertEqual(
                        LinuxUDPTraceStrategy().trace(ipaddress.ip_address("fd00::2"), 0.05), ()
                    )

    def test_trace_unexpected_failures_are_fatal_and_close_socket(self) -> None:
        for operation, number in (("setsockopt", errno.ENOBUFS), ("send", errno.EACCES)):
            with self.subTest(operation=operation), self.trace_socket() as (probe, _):
                getattr(probe, operation).side_effect = OSError(number, "probe failed")

                with self.assertRaisesRegex(HostCheckError, "UDP probe failed"):
                    LinuxUDPTraceStrategy().trace(ipaddress.ip_address("10.10.0.2"), 0.05)

    def test_trace_socket_creation_failure_is_fatal(self) -> None:
        with (
            patch(
                "engulf_clab_sticky_ip.probe_linux.socket.socket",
                side_effect=OSError(errno.EMFILE, "too many open files"),
            ),
            self.assertRaisesRegex(HostCheckError, "UDP probe failed"),
        ):
            LinuxUDPTraceStrategy().trace(ipaddress.ip_address("10.10.0.2"), 0.05)

    def test_trace_closes_socket_on_interrupt(self) -> None:
        with self.trace_socket() as (_, poller):
            poller.poll.side_effect = KeyboardInterrupt
            with self.assertRaises(KeyboardInterrupt):
                LinuxUDPTraceStrategy().trace(ipaddress.ip_address("10.10.0.2"), 0.05)

    def test_trace_rejects_truncated_error_metadata(self) -> None:
        with self.trace_socket() as (probe, poller):
            poller.poll.return_value = [(3, select.POLLERR)]
            probe.recvmsg.return_value = (b"", [], socket.MSG_CTRUNC, ())
            with self.assertRaisesRegex(HostCheckError, "truncated error metadata"):
                LinuxUDPTraceStrategy().trace(ipaddress.ip_address("10.10.0.2"), 0.05)

    def test_trace_reply_ignores_unrelated_control_messages(self) -> None:
        self.assertIsNone(_trace_reply([(socket.SOL_SOCKET, 11, b"ignored")], 4))

    def test_trace_reply_local_unreachable_has_no_offender(self) -> None:
        message = struct.pack("=IBBBBII", errno.ENETUNREACH, 1, 0, 0, 0, 0, 0)
        self.assertEqual(_trace_reply([(socket.IPPROTO_IP, 11, message)], 4), (None, True))

    def test_trace_reply_rejects_invalid_metadata(self) -> None:
        level, kind, data = self.error_message("10.10.0.2", 3)
        for malformed in (b"short", data[:16], data[:20]):
            with self.subTest(data=malformed), self.assertRaises(HostCheckError):
                _trace_reply([(level, kind, malformed)], 4)
