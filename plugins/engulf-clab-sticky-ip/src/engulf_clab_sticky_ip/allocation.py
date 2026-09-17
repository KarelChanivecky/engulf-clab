from __future__ import annotations

import hashlib
import ipaddress
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from engulf_clab_lab_parser import EffectiveNode, TopologyError, effective_nodes


class StickyIPError(RuntimeError):
    pass


class Family(StrEnum):
    IPV4 = "ipv4"
    IPV6 = "ipv6"

    @property
    def base_prefix(self) -> int:
        return 24 if self is Family.IPV4 else 120

    @property
    def subnet_field(self) -> str:
        return f"{self.value}-subnet"

    @property
    def gateway_field(self) -> str:
        return f"{self.value}-gw"

    @property
    def range_field(self) -> str:
        return f"{self.value}-range"

    @property
    def node_field(self) -> str:
        return f"mgmt-{self.value}"

    @property
    def version(self) -> int:
        return 4 if self is Family.IPV4 else 6


type Network = ipaddress.IPv4Network | ipaddress.IPv6Network
type Address = ipaddress.IPv4Address | ipaddress.IPv6Address

DEFAULT_IPV4_POOL = "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
DEFAULT_IPV6_POOL = "fd00::/8"
DEFAULT_MAX_LABS = 64
SLOTS_PER_UNIT = 128

_RFC1918 = tuple(
    ipaddress.IPv4Network(value)
    for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
_ULA = ipaddress.IPv6Network("fc00::/7")


@dataclass(frozen=True, slots=True)
class Config:
    max_labs: int
    ipv4_pools: tuple[ipaddress.IPv4Network, ...]
    ipv6_pools: tuple[ipaddress.IPv6Network, ...]
    exclusions: tuple[Network, ...]

    def pools(self, family: Family) -> tuple[Network, ...]:
        return self.ipv4_pools if family is Family.IPV4 else self.ipv6_pools


@dataclass(frozen=True, slots=True)
class TopologyRequest:
    name: str
    family: Family
    nodes: tuple[str, ...]
    network_name: str | None
    explicit_subnet: Network | None
    explicit_ips: Mapping[str, Address]

    @property
    def explicit(self) -> bool:
        return self.explicit_subnet is not None


def parse_bool(value: str | None, *, name: str) -> bool:
    if value is None or not value.strip():
        return False
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise StickyIPError(f"{name} must be a boolean")


def parse_config(environment: Mapping[str, str]) -> Config:
    raw_max = environment.get("ECLAB_STICKY_IP_MAX_LABS", str(DEFAULT_MAX_LABS))
    try:
        max_labs = int(raw_max)
    except ValueError as error:
        raise StickyIPError("ECLAB_STICKY_IP_MAX_LABS must be a positive integer") from error
    if max_labs <= 0:
        raise StickyIPError("ECLAB_STICKY_IP_MAX_LABS must be a positive integer")
    ipv4 = cast(
        tuple[ipaddress.IPv4Network, ...],
        _parse_pools(
            environment.get("ECLAB_STICKY_IPV4_POOL", DEFAULT_IPV4_POOL),
            Family.IPV4,
            "ECLAB_STICKY_IPV4_POOL",
        ),
    )
    ipv6 = cast(
        tuple[ipaddress.IPv6Network, ...],
        _parse_pools(
            environment.get("ECLAB_STICKY_IPV6_POOL", DEFAULT_IPV6_POOL),
            Family.IPV6,
            "ECLAB_STICKY_IPV6_POOL",
        ),
    )
    exclusions = _parse_exclusions(environment.get("ECLAB_STICKY_IP_EXCLUDES", ""))
    return Config(max_labs, ipv4, ipv6, exclusions)


def _parse_pools(value: str, family: Family, name: str) -> tuple[Network, ...]:
    items = _items(value, name)
    result: list[Network] = []
    for item in items:
        try:
            network = ipaddress.ip_network(item, strict=True)
        except ValueError as error:
            raise StickyIPError(f"{name} contains an invalid CIDR: {item!r}") from error
        if network.version != family.version:
            raise StickyIPError(f"{name} accepts only IPv{family.version} CIDRs")
        if network.prefixlen > family.base_prefix:
            raise StickyIPError(
                f"{name} entries must be large enough for a /{family.base_prefix} block"
            )
        if not private_network(network):
            raise StickyIPError(f"{name} accepts only private address space")
        if family is Family.IPV6 and any(network.network_address.packed[4:8]):
            raise StickyIPError(
                f"{name} cannot use bytes 5 through 8 of an IPv6 network prefix"
            )
        if any(network.overlaps(existing) for existing in result):
            raise StickyIPError(f"{name} contains duplicate or overlapping CIDRs")
        result.append(network)
    return tuple(result)


def _parse_exclusions(value: str) -> tuple[Network, ...]:
    if not value.strip():
        return ()
    result: list[Network] = []
    for item in _items(value, "ECLAB_STICKY_IP_EXCLUDES"):
        try:
            network = ipaddress.ip_network(item, strict=False)
        except ValueError as error:
            raise StickyIPError(
                f"ECLAB_STICKY_IP_EXCLUDES contains an invalid IP or CIDR: {item!r}"
            ) from error
        if not private_network(network):
            raise StickyIPError("ECLAB_STICKY_IP_EXCLUDES accepts only private addresses")
        result.append(network)
    return tuple(result)


def _items(value: str, name: str) -> tuple[str, ...]:
    result = tuple(item.strip() for item in value.split(",") if item.strip())
    if not result:
        raise StickyIPError(f"{name} must contain at least one CIDR")
    return result


def private_network(network: Network) -> bool:
    if isinstance(network, ipaddress.IPv4Network):
        return any(network.subnet_of(candidate) for candidate in _RFC1918)
    return network.subnet_of(_ULA)


def network_subnet_of(network: Network, container: Network) -> bool:
    if isinstance(network, ipaddress.IPv4Network):
        return isinstance(container, ipaddress.IPv4Network) and network.subnet_of(container)
    return isinstance(container, ipaddress.IPv6Network) and network.subnet_of(container)


def network_supernet_of(network: Network, contained: Network) -> bool:
    return network_subnet_of(contained, network)


def network_address_exclude(network: Network, excluded: Network) -> tuple[Network, ...]:
    if isinstance(network, ipaddress.IPv4Network):
        if not isinstance(excluded, ipaddress.IPv4Network):
            return (network,)
        return tuple(network.address_exclude(excluded))
    if not isinstance(excluded, ipaddress.IPv6Network):
        return (network,)
    return tuple(network.address_exclude(excluded))


def allocation_units(node_count: int) -> int:
    if node_count < 0:
        raise ValueError("node_count cannot be negative")
    needed = max(1, math.ceil(node_count / SLOTS_PER_UNIT))
    return 1 << (needed - 1).bit_length()


def allocation_prefix(family: Family, units: int) -> int:
    if units <= 0 or units & (units - 1):
        raise ValueError("allocation units must be a positive power of two")
    prefix = family.base_prefix - int(math.log2(units))
    if prefix < 0:
        raise StickyIPError("topology is too large for a sticky management subnet")
    return prefix


def lab_key(workspace: Path, name: str) -> str:
    return hashlib.sha256(f"{workspace.resolve()}\0{name}".encode()).hexdigest()


def generated_network_name(key: str) -> str:
    return f"eclab-mgmt-{key[:16]}"


def topology_request(document: Mapping[str, Any], family: Family) -> TopologyRequest:
    name = document.get("name")
    if not isinstance(name, str) or not name.strip():
        raise StickyIPError("topology must have a nonempty name")
    topology = document.get("topology")
    if not isinstance(topology, Mapping):
        raise StickyIPError("topology must contain a topology mapping")
    raw_nodes = topology.get("nodes")
    if not isinstance(raw_nodes, Mapping):
        raise StickyIPError("topology.nodes must be a mapping")
    nodes: list[str] = []
    node_data: dict[str, Mapping[str, Any]] = {}
    try:
        resolved = effective_nodes(document)
    except TopologyError as error:
        raise StickyIPError(str(error)) from error
    for effective in resolved:
        if _management_attached(effective):
            nodes.append(effective.name)
            node_data[effective.name] = effective.data

    mgmt_value = document.get("mgmt", {})
    if not isinstance(mgmt_value, Mapping):
        raise StickyIPError("mgmt must be a mapping")
    network_value = mgmt_value.get("network")
    if network_value is not None and (
        not isinstance(network_value, str) or not network_value.strip()
    ):
        raise StickyIPError("mgmt.network must be a nonempty string")
    network_name = network_value.strip() if isinstance(network_value, str) else None

    _validate_other_family(mgmt_value, node_data, family)
    selected_values = {
        key: mgmt_value.get(key)
        for key in (family.subnet_field, family.gateway_field, family.range_field)
        if key in mgmt_value
    }
    raw_ips = {
        node: fields.get(family.node_field)
        for node, fields in node_data.items()
        if family.node_field in fields
    }
    if not selected_values and not raw_ips:
        return TopologyRequest(
            name.strip(), family, tuple(sorted(nodes)), network_name, None, {}
        )

    subnet_value = selected_values.get(family.subnet_field)
    if subnet_value == "auto":
        raise StickyIPError(
            f"sticky IP rejects mgmt.{family.subnet_field}: auto; provide a complete "
            "fixed setup or use --eclab-no-sticky-ip"
        )
    if not isinstance(subnet_value, str):
        raise StickyIPError(
            f"partial sticky IP setup: mgmt.{family.subnet_field} and every "
            f"node {family.node_field} are required"
        )
    try:
        subnet = ipaddress.ip_network(subnet_value, strict=True)
    except ValueError as error:
        raise StickyIPError(f"invalid mgmt.{family.subnet_field}: {subnet_value!r}") from error
    if subnet.version != family.version or not private_network(subnet):
        raise StickyIPError(f"mgmt.{family.subnet_field} must be a private IPv{family.version} CIDR")
    if set(raw_ips) != set(nodes):
        raise StickyIPError(
            f"partial sticky IP setup: every management-attached node needs {family.node_field}"
        )
    explicit_ips: dict[str, Address] = {}
    for node, raw in raw_ips.items():
        if not isinstance(raw, str):
            raise StickyIPError(f"{node}.{family.node_field} must be an IP address")
        try:
            address = ipaddress.ip_address(raw)
        except ValueError as error:
            raise StickyIPError(f"invalid {node}.{family.node_field}: {raw!r}") from error
        if address.version != family.version or address not in subnet:
            raise StickyIPError(f"{node}.{family.node_field} must belong to {subnet}")
        explicit_ips[node] = address
    if len(set(explicit_ips.values())) != len(explicit_ips):
        raise StickyIPError(f"{family.node_field} addresses must be unique")
    reserved: set[Address] = {subnet.network_address + 1}
    if subnet.version == 4:
        reserved.update((subnet.network_address, subnet.broadcast_address))
    gateway = selected_values.get(family.gateway_field)
    if gateway is not None:
        try:
            parsed_gateway = ipaddress.ip_address(str(gateway))
        except ValueError as error:
            raise StickyIPError(f"invalid mgmt.{family.gateway_field}: {gateway!r}") from error
        if parsed_gateway.version != family.version or parsed_gateway not in subnet:
            raise StickyIPError(f"mgmt.{family.gateway_field} must belong to {subnet}")
        reserved.add(parsed_gateway)
    if any(address in reserved for address in explicit_ips.values()):
        raise StickyIPError(f"fixed {family.value} addresses cannot use reserved subnet addresses")
    return TopologyRequest(
        name.strip(), family, tuple(sorted(nodes)), network_name, subnet, explicit_ips
    )


def _validate_other_family(
    mgmt: Mapping[str, Any], nodes: Mapping[str, Mapping[str, Any]], selected: Family
) -> None:
    other = Family.IPV6 if selected is Family.IPV4 else Family.IPV4
    raw_ips = {node: value[other.node_field] for node, value in nodes.items() if other.node_field in value}
    subnet_value = mgmt.get(other.subnet_field)
    if not raw_ips:
        if subnet_value not in (None, "auto"):
            try:
                network = ipaddress.ip_network(str(subnet_value), strict=True)
            except ValueError as error:
                raise StickyIPError(f"invalid mgmt.{other.subnet_field}") from error
            if network.version != other.version or not private_network(network):
                raise StickyIPError(f"mgmt.{other.subnet_field} must be private")
        return
    if set(raw_ips) != set(nodes) or not isinstance(subnet_value, str) or subnet_value == "auto":
        raise StickyIPError(
            f"opposite-family addressing is incomplete; every attached node needs "
            f"{other.node_field} with mgmt.{other.subnet_field}"
        )
    try:
        subnet = ipaddress.ip_network(subnet_value, strict=True)
        addresses = tuple(ipaddress.ip_address(str(value)) for value in raw_ips.values())
    except ValueError as error:
        raise StickyIPError("opposite-family management addressing is invalid") from error
    if (
        subnet.version != other.version
        or not private_network(subnet)
        or any(address.version != other.version or address not in subnet for address in addresses)
        or len(set(addresses)) != len(addresses)
    ):
        raise StickyIPError("opposite-family management addressing is invalid")


def _management_attached(node: EffectiveNode) -> bool:
    mode = node.data.get("network-mode")
    return not (
        mode in {"host", "none"}
        or isinstance(mode, str)
        and mode.startswith("container:")
    )


def node_slots(subnet: Network) -> tuple[Address, ...]:
    family = Family.IPV4 if subnet.version == 4 else Family.IPV6
    if subnet.prefixlen > family.base_prefix:
        raise StickyIPError(f"{subnet} is too small for a 128-node logical block")
    result: list[Address] = []
    for unit in subnet.subnets(new_prefix=family.base_prefix):
        result.extend(unit.network_address + offset for offset in range(2, 130))
    return tuple(result)


def assign_node_ips(
    nodes: Sequence[str], subnet: Network, previous: Mapping[str, str]
) -> dict[str, str]:
    slots = node_slots(subnet)
    if len(nodes) > len(slots):
        raise StickyIPError(f"{subnet} has fewer than {len(nodes)} sticky node slots")
    allowed = set(slots)
    assigned: dict[str, Address] = {}
    used: set[Address] = set()
    for node in nodes:
        raw = previous.get(node)
        if raw is None:
            continue
        try:
            address = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if address in allowed and address not in used:
            assigned[node] = address
            used.add(address)
    available = iter(address for address in slots if address not in used)
    for node in nodes:
        if node not in assigned:
            assigned[node] = next(available)
    return {node: str(assigned[node]) for node in nodes}


def find_available_network(
    pools: Sequence[Network],
    prefix: int,
    blocked: Iterable[Network],
    *,
    cursor_pool: int = 0,
    cursor_address: int = -1,
) -> tuple[Network, int] | None:
    forbidden = tuple(blocked)
    after: list[tuple[int, int, Network]] = []
    wrapped: list[tuple[int, int, Network]] = []
    for pool_index, pool in enumerate(pools):
        if prefix < pool.prefixlen:
            continue
        fragments: list[Network] = [pool]
        for item in forbidden:
            if item.version != pool.version:
                continue
            next_fragments: list[Network] = []
            for fragment in fragments:
                if not fragment.overlaps(item):
                    next_fragments.append(fragment)
                elif item == fragment or network_supernet_of(item, fragment):
                    continue
                elif network_supernet_of(fragment, item):
                    next_fragments.extend(network_address_exclude(fragment, item))
            fragments = next_fragments
        for fragment in fragments:
            if fragment.prefixlen > prefix:
                continue
            candidate = _first_subnet(fragment, prefix)
            if candidate is None:
                continue
            key = (pool_index, int(candidate.network_address))
            wrapped.append((key[0], key[1], candidate))
            minimum = cursor_address + 1 if pool_index == cursor_pool else int(fragment.network_address)
            if pool_index < cursor_pool:
                continue
            if pool_index == cursor_pool:
                candidate = _first_subnet(fragment, prefix, minimum=minimum)
                if candidate is None:
                    continue
            after.append((pool_index, int(candidate.network_address), candidate))
    choices = sorted(after) or sorted(wrapped)
    if not choices:
        return None
    pool_index, _address, network = choices[0]
    return network, pool_index


def _first_subnet(
    fragment: Network, prefix: int, *, minimum: int | None = None
) -> Network | None:
    bits = fragment.max_prefixlen
    size = 1 << (bits - prefix)
    lower = max(int(fragment.network_address), minimum or 0)
    start = ((lower + size - 1) // size) * size
    end = start + size - 1
    if end > int(fragment.broadcast_address):
        return None
    candidate = ipaddress.ip_network((start, prefix))
    if candidate.version == 6 and any(candidate.network_address.packed[4:8]):
        return None
    return candidate
