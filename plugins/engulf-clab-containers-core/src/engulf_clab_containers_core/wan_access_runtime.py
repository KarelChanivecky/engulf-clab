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
_DHCP_ENVIRONMENT = frozenset(
    (_SUBNET_ENV, _GATEWAY_ENV, _POOL_START_ENV, _POOL_END_ENV, _DNS_ENV, _LEASE_TIME_ENV)
)

_DEFAULT_SUBNET = "198.19.0.0/24"
_DEFAULT_GATEWAY = "198.19.0.1"
_DEFAULT_POOL_START = "198.19.0.100"
_DEFAULT_POOL_END = "198.19.0.200"
_DEFAULT_DNS = "1.1.1.1"
_DEFAULT_LEASE_TIME = 12 * 60 * 60

_UPLINK = "eth0"
_NAT_CHAIN = "ECLAB_WAN_ACCESS_NAT"
_FORWARD_CHAIN = "ECLAB_WAN_ACCESS_FORWARD"
_READY = Path("/run/eclab-wan-access.ready")


class WanAccessError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DhcpConfig:
    subnet: ipaddress.IPv4Network
    gateway: ipaddress.IPv4Address
    pool_start: ipaddress.IPv4Address
    pool_end: ipaddress.IPv4Address
    dns: ipaddress.IPv4Address
    lease_time: int


def parse_dhcp_config(environment: dict[str, str]) -> DhcpConfig | None:
    if _DHCP_ENVIRONMENT.isdisjoint(environment):
        return None

    subnet_text = environment.get(_SUBNET_ENV, _DEFAULT_SUBNET)
    try:
        subnet = ipaddress.ip_network(subnet_text, strict=False)
    except ValueError as error:
        raise WanAccessError(f"{_SUBNET_ENV} must be an IPv4 CIDR network") from error
    if subnet.version != 4:
        raise WanAccessError(f"{_SUBNET_ENV} must be an IPv4 network")

    def parse_address(name: str, default: str) -> ipaddress.IPv4Address:
        text = environment.get(name, default)
        try:
            return ipaddress.IPv4Address(text)
        except ValueError as error:
            raise WanAccessError(f"{name} must be an IPv4 address") from error

    def address_in_subnet(name: str, default: str) -> ipaddress.IPv4Address:
        parsed = parse_address(name, default)
        if parsed not in subnet:
            raise WanAccessError(f"{name} must be inside {_SUBNET_ENV}")
        return parsed

    gateway = address_in_subnet(_GATEWAY_ENV, _DEFAULT_GATEWAY)
    pool_start = address_in_subnet(_POOL_START_ENV, _DEFAULT_POOL_START)
    pool_end = address_in_subnet(_POOL_END_ENV, _DEFAULT_POOL_END)
    if pool_start > pool_end:
        raise WanAccessError(f"{_POOL_START_ENV} must not exceed {_POOL_END_ENV}")
    if pool_start <= gateway <= pool_end:
        raise WanAccessError(f"{_GATEWAY_ENV} must fall outside the DHCP pool")

    dns = parse_address(_DNS_ENV, _DEFAULT_DNS)

    lease_text = environment.get(_LEASE_TIME_ENV, str(_DEFAULT_LEASE_TIME))
    try:
        lease_time = int(lease_text)
    except ValueError as error:
        raise WanAccessError(f"{_LEASE_TIME_ENV} must be an integer") from error
    if lease_time <= 0:
        raise WanAccessError(f"{_LEASE_TIME_ENV} must be positive")

    return DhcpConfig(subnet, gateway, pool_start, pool_end, dns, lease_time)


def lab_interfaces(root: Path = Path("/sys/class/net")) -> tuple[str, ...]:
    try:
        names = (item.name for item in root.iterdir())
    except OSError as error:
        raise WanAccessError(f"cannot enumerate network interfaces: {error}") from error
    return tuple(sorted(name for name in names if name not in {"lo", _UPLINK}))


def _run(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(arguments, check=check, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def _ensure_chain(table: str, parent: str, chain: str) -> None:
    _run("iptables", "-t", table, "-N", chain, check=False)
    _run("iptables", "-t", table, "-F", chain)
    present = _run("iptables", "-t", table, "-C", parent, "-j", chain, check=False)
    if present.returncode != 0:
        _run("iptables", "-t", table, "-A", parent, "-j", chain)


def configure_interface(interface: str) -> None:
    _run("ip", "link", "set", interface, "up")


def configure_dhcp_addressing(config: DhcpConfig, interface: str) -> None:
    _run("ip", "addr", "replace", f"{config.gateway}/{config.subnet.prefixlen}", "dev", interface)


def configure_nat(interface: str) -> None:
    _ensure_chain("nat", "POSTROUTING", _NAT_CHAIN)
    _ensure_chain("filter", "FORWARD", _FORWARD_CHAIN)
    _run(
        "iptables", "-t", "nat", "-A", _NAT_CHAIN,
        "-o", _UPLINK, "-j", "MASQUERADE",
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


def dnsmasq_arguments(config: DhcpConfig, interface: str) -> tuple[str, ...]:
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


def start_dhcp(config: DhcpConfig | None, interface: str) -> subprocess.Popen[bytes] | None:
    if config is None:
        return None
    return subprocess.Popen(dnsmasq_arguments(config, interface))


def wait_for_lab_interface() -> str:
    while True:
        interfaces = lab_interfaces()
        if len(interfaces) > 1:
            raise WanAccessError(
                f"exactly one lab-facing interface is required, found {', '.join(interfaces)}"
            )
        if interfaces:
            return interfaces[0]
        time.sleep(1)


def main() -> int:
    try:
        dhcp = parse_dhcp_config(dict(os.environ))
        interface = wait_for_lab_interface()
        configure_interface(interface)
        configure_nat(interface)
        if dhcp is not None:
            configure_dhcp_addressing(dhcp, interface)
        process = start_dhcp(dhcp, interface)
        _READY.touch()
    except (WanAccessError, OSError, subprocess.SubprocessError) as error:
        print(f"wan-access: {error}", file=sys.stderr, flush=True)
        return 1

    if dhcp is None:
        print(f"wan-access ready on {interface}; NAT enabled; DHCP disabled", flush=True)
        while True:
            time.sleep(3600)

    print(f"wan-access ready on {interface}; NAT and DHCP enabled", flush=True)
    assert process is not None
    return process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
