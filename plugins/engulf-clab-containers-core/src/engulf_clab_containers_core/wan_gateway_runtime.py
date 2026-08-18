from __future__ import annotations

import ipaddress
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_SUBNET_ENV = "ECLAB_DHCP_SUBNET"
_GATEWAY_ENV = "ECLAB_DHCP_GATEWAY"
_POOL_START_ENV = "ECLAB_DHCP_POOL_START"
_POOL_END_ENV = "ECLAB_DHCP_POOL_END"
_DNS_ENV = "ECLAB_DHCP_DNS"
_LEASE_TIME_ENV = "ECLAB_DHCP_LEASE_TIME"

_DEFAULT_SUBNET = "198.19.0.0/24"
_DEFAULT_GATEWAY = "198.19.0.1"
_DEFAULT_POOL_START = "198.19.0.100"
_DEFAULT_POOL_END = "198.19.0.200"
_DEFAULT_DNS = "1.1.1.1"
_DEFAULT_LEASE_TIME = 12 * 60 * 60

_UPLINK = "eth0"
_SNAT_CHAIN = "ECLAB_DHCP_SNAT"
_FORWARD_CHAIN = "ECLAB_DHCP_FORWARD"
_READY = Path("/run/eclab-dhcp-wan-gateway.ready")


class GatewayError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GatewayConfig:
    subnet: ipaddress.IPv4Network
    gateway: ipaddress.IPv4Address
    pool_start: ipaddress.IPv4Address
    pool_end: ipaddress.IPv4Address
    dns: ipaddress.IPv4Address
    lease_time: int


def parse_config(environment: dict[str, str]) -> GatewayConfig:
    subnet_text = environment.get(_SUBNET_ENV, _DEFAULT_SUBNET)
    try:
        subnet = ipaddress.ip_network(subnet_text, strict=False)
    except ValueError as error:
        raise GatewayError(f"{_SUBNET_ENV} must be an IPv4 CIDR network") from error
    if subnet.version != 4:
        raise GatewayError(f"{_SUBNET_ENV} must be an IPv4 network")

    def parse_address(name: str, default: str) -> ipaddress.IPv4Address:
        text = environment.get(name, default)
        try:
            return ipaddress.IPv4Address(text)
        except ValueError as error:
            raise GatewayError(f"{name} must be an IPv4 address") from error

    def address_in_subnet(name: str, default: str) -> ipaddress.IPv4Address:
        parsed = parse_address(name, default)
        if parsed not in subnet:
            raise GatewayError(f"{name} must be inside {_SUBNET_ENV}")
        return parsed

    gateway = address_in_subnet(_GATEWAY_ENV, _DEFAULT_GATEWAY)
    pool_start = address_in_subnet(_POOL_START_ENV, _DEFAULT_POOL_START)
    pool_end = address_in_subnet(_POOL_END_ENV, _DEFAULT_POOL_END)
    if pool_start > pool_end:
        raise GatewayError(f"{_POOL_START_ENV} must not exceed {_POOL_END_ENV}")
    if pool_start <= gateway <= pool_end:
        raise GatewayError(f"{_GATEWAY_ENV} must fall outside the DHCP pool")

    dns = parse_address(_DNS_ENV, _DEFAULT_DNS)

    lease_text = environment.get(_LEASE_TIME_ENV, str(_DEFAULT_LEASE_TIME))
    try:
        lease_time = int(lease_text)
    except ValueError as error:
        raise GatewayError(f"{_LEASE_TIME_ENV} must be an integer") from error
    if lease_time <= 0:
        raise GatewayError(f"{_LEASE_TIME_ENV} must be positive")

    return GatewayConfig(subnet, gateway, pool_start, pool_end, dns, lease_time)


def lab_interfaces(root: Path = Path("/sys/class/net")) -> tuple[str, ...]:
    try:
        names = (item.name for item in root.iterdir())
    except OSError as error:
        raise GatewayError(f"cannot enumerate network interfaces: {error}") from error
    return tuple(sorted(name for name in names if name not in {"lo", _UPLINK}))


def _run(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(arguments, check=check, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def _ensure_chain(table: str, parent: str, chain: str) -> None:
    _run("iptables", "-t", table, "-N", chain, check=False)
    _run("iptables", "-t", table, "-F", chain)
    present = _run("iptables", "-t", table, "-C", parent, "-j", chain, check=False)
    if present.returncode != 0:
        _run("iptables", "-t", table, "-A", parent, "-j", chain)


def configure_addressing(config: GatewayConfig, interface: str) -> None:
    _run("ip", "addr", "replace", f"{config.gateway}/{config.subnet.prefixlen}", "dev", interface)
    _run("ip", "link", "set", interface, "up")


def configure_nat(config: GatewayConfig, interface: str) -> None:
    _ensure_chain("nat", "POSTROUTING", _SNAT_CHAIN)
    _ensure_chain("filter", "FORWARD", _FORWARD_CHAIN)
    _run(
        "iptables", "-t", "nat", "-A", _SNAT_CHAIN,
        "-s", str(config.subnet), "-o", _UPLINK, "-j", "MASQUERADE",
    )
    _run(
        "iptables", "-A", _FORWARD_CHAIN,
        "-i", interface, "-o", _UPLINK, "-j", "ACCEPT",
    )
    _run(
        "iptables", "-A", _FORWARD_CHAIN,
        "-i", _UPLINK, "-o", interface,
        "-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "ACCEPT",
    )


def dnsmasq_arguments(config: GatewayConfig, interface: str) -> tuple[str, ...]:
    return (
        "dnsmasq",
        "--no-daemon",
        "--log-facility=-",
        "--port=0",
        f"--interface={interface}",
        "--bind-interfaces",
        "--dhcp-authoritative",
        f"--dhcp-range={config.pool_start},{config.pool_end},{config.lease_time}s",
        f"--dhcp-option=option:router,{config.gateway}",
        f"--dhcp-option=option:dns-server,{config.dns}",
    )


def wait_for_lab_interface() -> str:
    while True:
        interfaces = lab_interfaces()
        if len(interfaces) > 1:
            raise GatewayError(
                f"exactly one lab-facing interface is required, found {', '.join(interfaces)}"
            )
        if interfaces:
            return interfaces[0]
        time.sleep(1)


def main() -> int:
    try:
        config = parse_config(dict(os.environ))
        interface = wait_for_lab_interface()
        configure_addressing(config, interface)
        configure_nat(config, interface)
    except (GatewayError, OSError, subprocess.SubprocessError) as error:
        print(f"dhcp-wan-gateway: {error}", file=sys.stderr, flush=True)
        return 1

    process = subprocess.Popen(dnsmasq_arguments(config, interface))
    _READY.touch()
    print(
        f"dhcp-wan-gateway ready on {interface} subnet={config.subnet} gateway={config.gateway}",
        flush=True,
    )
    return process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
