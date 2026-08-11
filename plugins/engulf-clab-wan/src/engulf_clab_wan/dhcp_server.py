from __future__ import annotations

import argparse
import ipaddress
import json
import os
import socket
import struct
import time
from dataclasses import dataclass
from pathlib import Path

from .errors import WanError

MAGIC_COOKIE = b"\x63\x82\x53\x63"
DHCP_DISCOVER = 1
DHCP_OFFER = 2
DHCP_REQUEST = 3
DHCP_ACK = 5
DHCP_NAK = 6
ETH_P_IP = 0x0800
IP_PROTO_UDP = 17


def log(message: str) -> None:
    print(f"dhcp-server: {message}", flush=True)


@dataclass(frozen=True)
class ServerConfig:
    interface: str
    gateway: ipaddress.IPv4Address
    subnet: ipaddress.IPv4Network
    pool_start: ipaddress.IPv4Address
    pool_end: ipaddress.IPv4Address
    dns: ipaddress.IPv4Address
    lease_time: int
    lease_file: Path

    @property
    def netmask(self) -> ipaddress.IPv4Address:
        return self.subnet.netmask


def ip_bytes(address: ipaddress.IPv4Address) -> bytes:
    return address.packed


def iface_mac(interface: str) -> bytes:
    path = Path("/sys/class/net") / interface / "address"
    value = path.read_text(encoding="utf-8").strip()
    return bytes(int(part, 16) for part in value.split(":"))


def checksum(payload: bytes) -> int:
    if len(payload) % 2:
        payload += b"\x00"
    total = 0
    for index in range(0, len(payload), 2):
        total += (payload[index] << 8) + payload[index + 1]
    while total > 0xFFFF:
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


def mac_key(chaddr: bytes) -> str:
    return ":".join(f"{byte:02x}" for byte in chaddr[:6])


def parse_options(payload: bytes) -> dict[int, list[bytes]]:
    options: dict[int, list[bytes]] = {}
    if len(payload) < 240 or payload[236:240] != MAGIC_COOKIE:
        return options

    index = 240
    while index < len(payload):
        code = payload[index]
        index += 1
        if code == 255:
            break
        if code == 0:
            continue
        if index >= len(payload):
            break
        length = payload[index]
        index += 1
        value = payload[index : index + length]
        index += length
        options.setdefault(code, []).append(value)
    return options


def option(options: dict[int, list[bytes]], code: int) -> bytes | None:
    values = options.get(code)
    return values[-1] if values else None


def option_ip(
    options: dict[int, list[bytes]], code: int
) -> ipaddress.IPv4Address | None:
    value = option(options, code)
    if value is None or len(value) != 4:
        return None
    return ipaddress.IPv4Address(value)


def dhcp_message_type(options: dict[int, list[bytes]]) -> int | None:
    value = option(options, 53)
    if value is None or len(value) != 1:
        return None
    return value[0]


def load_leases(path: Path) -> dict[str, dict[str, float | str]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return {}
    return data


def save_leases(path: Path, leases: dict[str, dict[str, float | str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = path.with_suffix(path.suffix + ".tmp")
    with tmp_file.open("w", encoding="utf-8") as handle:
        json.dump(leases, handle, indent=2, sort_keys=True)
        handle.write("\n")
    tmp_file.replace(path)


def lease_valid(lease: dict[str, float | str], now: float) -> bool:
    expires = lease.get("expires")
    return isinstance(expires, (int, float)) and expires > now


def ip_in_pool(config: ServerConfig, address: ipaddress.IPv4Address) -> bool:
    return config.pool_start <= address <= config.pool_end


def allocate_address(
    config: ServerConfig,
    leases: dict[str, dict[str, float | str]],
    key: str,
    requested: ipaddress.IPv4Address | None,
) -> ipaddress.IPv4Address:
    now = time.time()
    existing = leases.get(key)
    if existing and lease_valid(existing, now):
        current = ipaddress.IPv4Address(str(existing.get("address")))
        if ip_in_pool(config, current):
            return current

    if requested is not None and ip_in_pool(config, requested):
        owner = None
        for mac, lease in leases.items():
            if (
                mac != key
                and lease_valid(lease, now)
                and lease.get("address") == str(requested)
            ):
                owner = mac
                break
        if owner is None:
            return requested

    used = {
        str(lease.get("address"))
        for lease in leases.values()
        if lease_valid(lease, now)
    }
    for value in range(int(config.pool_start), int(config.pool_end) + 1):
        address = ipaddress.IPv4Address(value)
        if str(address) not in used:
            return address
    raise WanError(f"no DHCP leases available on {config.interface}")


def record_lease(
    leases: dict[str, dict[str, float | str]],
    key: str,
    address: ipaddress.IPv4Address,
    lease_time: int,
) -> None:
    leases[key] = {
        "address": str(address),
        "expires": time.time() + lease_time,
    }


def make_options(config: ServerConfig, message_type: int) -> bytes:
    values = [
        bytes([53, 1, message_type]),
        bytes([54, 4]) + ip_bytes(config.gateway),
        bytes([1, 4]) + ip_bytes(config.netmask),
        bytes([3, 4]) + ip_bytes(config.gateway),
        bytes([6, 4]) + ip_bytes(config.dns),
        bytes([51, 4]) + struct.pack("!I", config.lease_time),
    ]
    return MAGIC_COOKIE + b"".join(values) + b"\xff"


def make_reply(
    request: bytes,
    config: ServerConfig,
    yiaddr: ipaddress.IPv4Address,
    message_type: int,
) -> bytes:
    _op, htype, hlen, _hops, xid, _secs, _flags = struct.unpack(
        "!BBBBIHH", request[:12]
    )
    chaddr = request[28:44]
    header = struct.pack(
        "!BBBBIHH4s4s4s4s16s64s128s",
        2,
        htype,
        hlen,
        0,
        xid,
        0,
        0x8000,
        b"\x00\x00\x00\x00",
        ip_bytes(yiaddr),
        ip_bytes(config.gateway),
        b"\x00\x00\x00\x00",
        chaddr,
        b"\x00" * 64,
        b"\x00" * 128,
    )
    return header + make_options(config, message_type)


def dhcp_payload_from_frame(frame: bytes) -> bytes | None:
    if len(frame) < 14:
        return None
    ethertype = struct.unpack("!H", frame[12:14])[0]
    if ethertype != ETH_P_IP:
        return None

    ip_start = 14
    if len(frame) < ip_start + 20:
        return None
    first = frame[ip_start]
    version = first >> 4
    ihl = (first & 0x0F) * 4
    if version != 4 or ihl < 20:
        return None
    protocol = frame[ip_start + 9]
    if protocol != IP_PROTO_UDP:
        return None

    total_length = struct.unpack("!H", frame[ip_start + 2 : ip_start + 4])[0]
    udp_start = ip_start + ihl
    if len(frame) < udp_start + 8:
        return None
    source_port, destination_port, udp_length, _checksum = struct.unpack(
        "!HHHH",
        frame[udp_start : udp_start + 8],
    )
    if source_port != 68 or destination_port != 67:
        return None

    ip_end = ip_start + total_length
    payload_start = udp_start + 8
    payload_end = min(ip_end, payload_start + udp_length - 8, len(frame))
    return frame[payload_start:payload_end]


def make_frame(config: ServerConfig, source_mac: bytes, dhcp_payload: bytes) -> bytes:
    destination_mac = b"\xff" * 6
    ethernet = destination_mac + source_mac + struct.pack("!H", ETH_P_IP)

    udp_length = 8 + len(dhcp_payload)
    total_length = 20 + udp_length
    ip_without_checksum = struct.pack(
        "!BBHHHBBH4s4s",
        0x45,
        0,
        total_length,
        0,
        0,
        64,
        IP_PROTO_UDP,
        0,
        ip_bytes(config.gateway),
        b"\xff\xff\xff\xff",
    )
    ip_header = struct.pack(
        "!BBHHHBBH4s4s",
        0x45,
        0,
        total_length,
        0,
        0,
        64,
        IP_PROTO_UDP,
        checksum(ip_without_checksum),
        ip_bytes(config.gateway),
        b"\xff\xff\xff\xff",
    )
    udp_header = struct.pack("!HHHH", 67, 68, udp_length, 0)
    return ethernet + ip_header + udp_header + dhcp_payload


def serve(config: ServerConfig) -> None:
    log(
        f"starting interface={config.interface} subnet={config.subnet} "
        f"gateway={config.gateway} pool={config.pool_start}-{config.pool_end}"
    )
    leases = load_leases(config.lease_file)
    mac = iface_mac(config.interface)
    sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_IP))
    sock.bind((config.interface, 0))
    log("listening for DHCP frames")

    while True:
        frame, _peer = sock.recvfrom(4096)
        payload = dhcp_payload_from_frame(frame)
        if payload is None or len(payload) < 240:
            continue
        options = parse_options(payload)
        message_type = dhcp_message_type(options)
        if message_type not in (DHCP_DISCOVER, DHCP_REQUEST):
            continue

        key = mac_key(payload[28:44])
        log(f"received message_type={message_type} client={key}")
        requested = option_ip(options, 50)
        if requested is None:
            ciaddr = ipaddress.IPv4Address(payload[12:16])
            requested = ciaddr if ciaddr != ipaddress.IPv4Address("0.0.0.0") else None

        try:
            yiaddr = allocate_address(config, leases, key, requested)
        except WanError:
            log(f"no lease available client={key}; sending NAK")
            reply = make_reply(payload, config, config.gateway, DHCP_NAK)
            sock.send(make_frame(config, mac, reply))
            continue

        if message_type == DHCP_REQUEST:
            record_lease(leases, key, yiaddr, config.lease_time)
            save_leases(config.lease_file, leases)
            reply_type = DHCP_ACK
        else:
            reply_type = DHCP_OFFER

        reply = make_reply(payload, config, yiaddr, reply_type)
        sock.send(make_frame(config, mac, reply))
        log(f"sent message_type={reply_type} client={key} address={yiaddr}")


def config_from_file(path: Path) -> ServerConfig:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)

    subnet = ipaddress.IPv4Network(str(data["subnet"]), strict=False)
    return ServerConfig(
        interface=str(data["interface"]),
        gateway=ipaddress.IPv4Address(str(data["gateway"])),
        subnet=subnet,
        pool_start=ipaddress.IPv4Address(str(data["pool_start"])),
        pool_end=ipaddress.IPv4Address(str(data["pool_end"])),
        dns=ipaddress.IPv4Address(str(data["dns"])),
        lease_time=int(data["lease_time"]),
        lease_file=Path(str(data["lease_file"])),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("pid_file")
    args = parser.parse_args(argv)

    config = config_from_file(Path(args.config))
    pid_file = Path(args.pid_file)
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(
        json.dumps({"config": args.config, "pid": os.getpid()}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    serve(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
