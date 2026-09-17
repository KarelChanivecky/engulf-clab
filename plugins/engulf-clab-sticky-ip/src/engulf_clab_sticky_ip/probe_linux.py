from __future__ import annotations

import errno
import ipaddress
import math
import select
import socket
import struct
import time
from collections.abc import Iterable

from .allocation import Address
from .errors import HostCheckError, ProbeUnavailableError

# Linux UAPI values; Python only exposes these socket options starting in 3.14.
_IP_RECVERR = getattr(socket, "IP_RECVERR", 11)
_IPV6_RECVERR = getattr(socket, "IPV6_RECVERR", 25)
_EXTENDED_ERROR = struct.Struct("=IBBBBII")
_UNREACHABLE = frozenset({errno.ENETUNREACH, errno.EHOSTUNREACH})
_UNSUPPORTED = frozenset(
    {
        errno.ENOPROTOOPT,
        errno.EOPNOTSUPP,
        errno.EAFNOSUPPORT,
        errno.EPROTONOSUPPORT,
        errno.ENOSYS,
    }
)


class LinuxUDPTraceStrategy:
    def trace(self, target: Address, timeout: float) -> tuple[Address, ...]:
        """Collect up to eight UDP trace hops without raw sockets or subprocesses.

        Each connected socket has its own ephemeral source port, so the kernel
        delivers only this trace's ICMP errors to its error queue. POLLERR wakes us
        for those errors even though the socket has no ordinary readable payload.
        """
        deadline = time.monotonic() + timeout
        hops: list[Address] = []
        if timeout <= 0:
            return ()
        ipv4 = target.version == 4
        family = socket.AF_INET if ipv4 else socket.AF_INET6
        level = socket.IPPROTO_IP if ipv4 else socket.IPPROTO_IPV6
        receive_error = _IP_RECVERR if ipv4 else _IPV6_RECVERR
        hop_limit = socket.IP_TTL if ipv4 else socket.IPV6_UNICAST_HOPS
        try:
            with socket.socket(family, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as probe:
                probe.setblocking(False)
                probe.setsockopt(level, receive_error, 1)
                probe.connect((str(target), 33434))
                poller = select.poll()
                poller.register(probe, select.POLLIN | select.POLLERR)
                for hop in range(1, 9):
                    if time.monotonic() >= deadline:
                        break
                    probe.setsockopt(level, hop_limit, hop)
                    probe.send(b"sticky-ip")
                    while (remaining := deadline - time.monotonic()) > 0:
                        events = poller.poll(math.ceil(remaining * 1000))
                        if not events:
                            return tuple(hops)
                        flags = events[0][1]
                        if flags & (select.POLLNVAL | select.POLLHUP):
                            raise HostCheckError("sticky IP UDP probe socket became unavailable")
                        if flags & select.POLLERR:
                            try:
                                _, ancillary, message_flags, _ = probe.recvmsg(
                                    512,
                                    socket.CMSG_SPACE(128),
                                    socket.MSG_ERRQUEUE | socket.MSG_DONTWAIT,
                                )
                            except BlockingIOError:
                                continue
                            if message_flags & socket.MSG_CTRUNC:
                                raise HostCheckError(
                                    "sticky IP UDP probe received truncated error metadata"
                                )
                            reply = _trace_reply(ancillary, target.version)
                            if reply is None:
                                continue
                            address, terminal = reply
                            if address is not None:
                                hops.append(address)
                            if terminal:
                                return tuple(hops)
                            break
                        if flags & select.POLLIN:
                            try:
                                probe.recv(512)
                            except BlockingIOError:
                                continue
                            # A normal UDP reply from the connected destination is
                            # just as conclusive as an ICMP port-unreachable reply.
                            hops.append(target)
                            return tuple(hops)
                    else:
                        break
        except OSError as error:
            if error.errno in _UNSUPPORTED:
                raise ProbeUnavailableError(f"Linux UDP probes are unavailable: {error}") from error
            if error.errno not in _UNREACHABLE:
                raise HostCheckError(f"sticky IP UDP probe failed: {error}") from error
        return tuple(hops)


def _trace_reply(
    ancillary: Iterable[tuple[int, int, bytes]], version: int
) -> tuple[Address | None, bool] | None:
    """Decode Linux sock_extended_err and its following offender sockaddr."""
    ipv4 = version == 4
    level = socket.IPPROTO_IP if ipv4 else socket.IPPROTO_IPV6
    receive_error = _IP_RECVERR if ipv4 else _IPV6_RECVERR
    for message_level, message_type, data in ancillary:
        if (message_level, message_type) != (level, receive_error):
            continue
        if len(data) < _EXTENDED_ERROR.size:
            raise HostCheckError("sticky IP UDP probe received invalid error metadata")
        number, origin, kind, _code, _pad, _info, _data = _EXTENDED_ERROR.unpack_from(data)
        if origin == 1:  # SO_EE_ORIGIN_LOCAL has no responding router.
            if number not in _UNREACHABLE:
                raise OSError(number, "local UDP probe error")
            return None, True
        if origin != (2 if ipv4 else 3):  # SO_EE_ORIGIN_ICMP / SO_EE_ORIGIN_ICMP6
            continue
        offender = data[_EXTENDED_ERROR.size :]
        if len(offender) < 2:
            raise HostCheckError("sticky IP UDP probe received invalid offender metadata")
        offender_family = struct.unpack_from("=H", offender)[0]
        terminal = kind != (11 if ipv4 else 3)  # ICMP time exceeded permits the next hop.
        if offender_family == socket.AF_UNSPEC:
            return None, terminal
        offset, length = (4, 4) if ipv4 else (8, 16)
        if (
            offender_family != (socket.AF_INET if ipv4 else socket.AF_INET6)
            or len(offender) < offset + length
        ):
            raise HostCheckError("sticky IP UDP probe received invalid offender metadata")
        return ipaddress.ip_address(offender[offset : offset + length]), terminal
    return None
