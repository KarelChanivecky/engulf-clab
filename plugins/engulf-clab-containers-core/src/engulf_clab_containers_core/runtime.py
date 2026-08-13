from __future__ import annotations

import ipaddress
import os
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

_PREFIX = "ECLAB_CONNECT_HOST"
_READY = Path("/run/eclab-host-connector.ready")


class ConnectorError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Mapping:
    index: int
    vip: ipaddress.IPv4Address | ipaddress.IPv6Address
    target: ipaddress.IPv4Address | ipaddress.IPv6Address


def parse_mappings(environment: dict[str, str]) -> tuple[Mapping, ...]:
    indexed: dict[int, tuple[str, str]] = {}
    if _PREFIX in environment and f"{_PREFIX}_0" in environment:
        raise ConnectorError(f"{_PREFIX} and {_PREFIX}_0 are aliases and cannot both be set")
    for name, value in environment.items():
        if name == _PREFIX:
            index = 0
        elif name.startswith(f"{_PREFIX}_"):
            suffix = name.removeprefix(f"{_PREFIX}_")
            if not suffix.isdigit():
                continue
            index = int(suffix)
        else:
            continue
        pieces = value.split(";")
        if len(pieces) != 2 or not all(piece.strip() for piece in pieces):
            raise ConnectorError(f"{name} must use <vip>;<external-ip>")
        indexed[index] = (name, value)
    if not indexed:
        raise ConnectorError(f"at least one {_PREFIX} mapping is required")
    result: list[Mapping] = []
    seen_vips: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for index, (name, value) in sorted(indexed.items()):
        vip_text, target_text = (piece.strip() for piece in value.split(";"))
        try:
            vip = ipaddress.ip_address(vip_text)
            target = ipaddress.ip_address(target_text)
        except ValueError as error:
            raise ConnectorError(f"{name} must contain two IP addresses") from error
        if vip.version != target.version:
            raise ConnectorError(f"{name} VIP and external IP must use the same address family")
        if vip == target:
            raise ConnectorError(f"{name} VIP and external IP must differ")
        if vip in seen_vips:
            raise ConnectorError(f"duplicate VIP {vip}")
        seen_vips.add(vip)
        result.append(Mapping(index, vip, target))
    return tuple(result)


def data_interfaces(root: Path = Path("/sys/class/net")) -> tuple[str, ...]:
    try:
        names = (item.name for item in root.iterdir())
    except OSError as error:
        raise ConnectorError(f"cannot enumerate network interfaces: {error}") from error
    return tuple(sorted(name for name in names if name not in {"lo", "eth0"}))


def _run(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(arguments, check=check, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def _write_sysctl(family: str, interface: str, setting: str, value: str) -> None:
    path = Path("/proc/sys/net") / family / "conf" / interface / setting
    try:
        path.write_text(value + "\n", encoding="ascii")
    except OSError as error:
        raise ConnectorError(f"cannot set {path}: {error}") from error


def _ensure_chain(command: str, table: str, parent: str, chain: str) -> None:
    _run(command, "-t", table, "-N", chain, check=False)
    _run(command, "-t", table, "-F", chain)
    present = _run(command, "-t", table, "-C", parent, "-j", chain, check=False)
    if present.returncode != 0:
        _run(command, "-t", table, "-A", parent, "-j", chain)


def _configure_family(
    version: int,
    mappings: tuple[Mapping, ...],
    interfaces: tuple[str, ...],
) -> None:
    selected = tuple(item for item in mappings if item.vip.version == version)
    if not selected:
        return
    firewall = "iptables" if version == 4 else "ip6tables"
    family = "-4" if version == 4 else "-6"
    prefix = "32" if version == 4 else "128"
    _ensure_chain(firewall, "nat", "PREROUTING", "ECLAB_DNAT")
    _ensure_chain(firewall, "nat", "POSTROUTING", "ECLAB_SNAT")
    _ensure_chain(firewall, "mangle", "PREROUTING", "ECLAB_MARK")
    _ensure_chain(firewall, "filter", "FORWARD", "ECLAB_FORWARD")
    _run(firewall, "-t", "mangle", "-A", "ECLAB_MARK", "-j", "CONNMARK", "--restore-mark")
    for mapping in selected:
        _run("ip", family, "address", "replace", f"{mapping.vip}/{prefix}", "dev", "lo")
    for interface in interfaces:
        interface_index = socket.if_nametoindex(interface)
        mark = 1000 + interface_index
        table = 10000 + interface_index
        _run("ip", family, "route", "replace", "default", "dev", interface, "table", str(table))
        rule = _run(
            "ip",
            family,
            "rule",
            "add",
            "fwmark",
            str(mark),
            "lookup",
            str(table),
            "priority",
            str(table),
            check=False,
        )
        if rule.returncode != 0 and b"File exists" not in rule.stderr:
            raise ConnectorError(rule.stderr.decode(errors="replace").strip())
        for mapping in selected:
            _run("ip", family, "neigh", "replace", "proxy", str(mapping.vip), "dev", interface)
            _run(
                firewall,
                "-t",
                "nat",
                "-A",
                "ECLAB_DNAT",
                "-i",
                interface,
                "-d",
                str(mapping.vip),
                "-j",
                "DNAT",
                "--to-destination",
                str(mapping.target),
            )
            _run(
                firewall,
                "-t",
                "mangle",
                "-A",
                "ECLAB_MARK",
                "-i",
                interface,
                "-d",
                str(mapping.vip),
                "-m",
                "conntrack",
                "--ctstate",
                "NEW",
                "-j",
                "MARK",
                "--set-mark",
                str(mark),
            )
            _run(
                firewall,
                "-t",
                "filter",
                "-A",
                "ECLAB_FORWARD",
                "-i",
                interface,
                "-o",
                "eth0",
                "-d",
                str(mapping.target),
                "-m",
                "conntrack",
                "--ctstate",
                "NEW",
                "-j",
                "ACCEPT",
            )
        _run(firewall, "-t", "filter", "-A", "ECLAB_FORWARD", "-i", interface, "-j", "DROP")
    _run(
        firewall,
        "-t",
        "mangle",
        "-A",
        "ECLAB_MARK",
        "-m",
        "mark",
        "!",
        "--mark",
        "0",
        "-j",
        "CONNMARK",
        "--save-mark",
    )
    _run(
        firewall,
        "-t",
        "filter",
        "-I",
        "ECLAB_FORWARD",
        "1",
        "-m",
        "mark",
        "!",
        "--mark",
        "0",
        "-m",
        "conntrack",
        "--ctstate",
        "ESTABLISHED,RELATED",
        "-j",
        "ACCEPT",
    )
    for target in sorted({str(item.target) for item in selected}):
        _run(
            firewall,
            "-t",
            "nat",
            "-A",
            "ECLAB_SNAT",
            "-o",
            "eth0",
            "-d",
            target,
            "-j",
            "MASQUERADE",
        )


def configure(mappings: tuple[Mapping, ...], interfaces: tuple[str, ...]) -> None:
    for interface in interfaces:
        _write_sysctl("ipv4", interface, "proxy_arp", "1")
        _write_sysctl("ipv4", interface, "rp_filter", "0")
        _write_sysctl("ipv6", interface, "proxy_ndp", "1")
    _configure_family(4, mappings, interfaces)
    _configure_family(6, mappings, interfaces)


def main() -> int:
    try:
        mappings = parse_mappings(dict(os.environ))
        configured: tuple[str, ...] = ()
        while True:
            interfaces = data_interfaces()
            if interfaces and interfaces != configured:
                configure(mappings, interfaces)
                configured = interfaces
                _READY.touch()
                print(f"host-connector ready on {', '.join(interfaces)}", flush=True)
            time.sleep(1)
    except (ConnectorError, OSError, subprocess.SubprocessError) as error:
        print(f"host-connector: {error}", file=os.sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
