from __future__ import annotations

import ipaddress
import json
import subprocess
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .allocation import Address, Network, node_slots
from .errors import HostCheckError
from .probes import TraceStrategy, select_trace_strategy


@dataclass(frozen=True, slots=True)
class Owner:
    lab_name: str
    topology_directory: Path | None

    def is_lab(self, name: str, workspace: Path) -> bool:
        return self.lab_name == name and self.topology_directory == workspace.resolve()


@dataclass(frozen=True, slots=True)
class ObservedNetwork:
    network_id: str
    name: str
    subnets: tuple[Network, ...]
    gateways: tuple[Address, ...]
    endpoints: dict[Address, Owner | None]
    bridge: str | None

    def belongs_to(self, name: str, workspace: Path, owned_names: set[str]) -> bool:
        if self.name not in owned_names and not self.endpoints:
            return False
        return all(
            owner is not None and owner.is_lab(name, workspace)
            for owner in self.endpoints.values()
        )


@dataclass(frozen=True, slots=True)
class ObservedRoute:
    network: Network
    device: str | None


@dataclass(frozen=True, slots=True)
class HostInventory:
    networks: tuple[ObservedNetwork, ...]
    routes: tuple[ObservedRoute, ...]

    def blocked_networks(
        self,
        *,
        lab_name: str,
        workspace: Path,
        owned_names: set[str],
    ) -> tuple[Network, ...]:
        own_bridges = {
            network.bridge
            for network in self.networks
            if network.belongs_to(lab_name, workspace, owned_names) and network.bridge
        }
        blocked: list[Network] = []
        for network in self.networks:
            if not network.belongs_to(lab_name, workspace, owned_names):
                blocked.extend(network.subnets)
        blocked.extend(
            route.network for route in self.routes if route.device not in own_bridges
        )
        return tuple(blocked)

    def validate_candidate(
        self,
        candidate: Network,
        *,
        network_name: str,
        lab_name: str,
        workspace: Path,
        owned_names: set[str],
        destructive: bool,
    ) -> frozenset[Address]:
        own_addresses: set[Address] = set()
        own_bridges: set[str] = set()
        named = [network for network in self.networks if network.name == network_name]
        for network in named:
            owned = network.belongs_to(lab_name, workspace, owned_names)
            if not owned:
                raise HostCheckError(
                    f"management network {network_name!r} already exists and is not owned by this lab"
                )
            same_family = tuple(item for item in network.subnets if item.version == candidate.version)
            if candidate not in same_family and not destructive:
                raise HostCheckError(
                    f"management network {network_name!r} uses a different subnet; "
                    "use redeploy or deploy --reconfigure"
                )
            own_addresses.update(network.gateways)
            own_addresses.update(network.endpoints)
            if network.bridge:
                own_bridges.add(network.bridge)

        for network in self.networks:
            for subnet in network.subnets:
                if subnet.version != candidate.version or not subnet.overlaps(candidate):
                    continue
                owned = network.belongs_to(lab_name, workspace, owned_names)
                if network.name != network_name or not owned:
                    raise HostCheckError(
                        f"candidate subnet {candidate} overlaps Docker network {network.name!r} ({subnet})"
                    )
                if subnet != candidate and not destructive:
                    raise HostCheckError(
                        f"candidate subnet {candidate} overlaps this lab's existing {subnet}; "
                        "use redeploy or deploy --reconfigure"
                    )
        for route in self.routes:
            if route.network.version != candidate.version or not route.network.overlaps(candidate):
                continue
            if route.device not in own_bridges:
                raise HostCheckError(
                    f"candidate subnet {candidate} overlaps host route {route.network}"
                )
        return frozenset(
            address for address in own_addresses if address.version == candidate.version
        )


def inspect_host() -> HostInventory:
    network_ids = _run(("docker", "network", "ls", "--quiet", "--no-trunc")).split()
    raw_networks: list[dict[str, Any]] = []
    if network_ids:
        payload = _json(
            _run(("docker", "network", "inspect", *network_ids)),
            "docker network inspect",
        )
        if not isinstance(payload, list):
            raise HostCheckError("docker network inspect returned invalid JSON")
        raw_networks = [item for item in payload if isinstance(item, dict)]
    container_ids = sorted(
        {
            identifier
            for network in raw_networks
            for identifier in _container_ids(network)
        }
    )
    owners = _container_owners(container_ids)
    networks = tuple(_network(item, owners) for item in raw_networks)
    routes = (*_routes(4), *_routes(6))
    return HostInventory(networks, routes)


def _container_ids(network: dict[str, Any]) -> tuple[str, ...]:
    containers = network.get("Containers")
    if not isinstance(containers, dict):
        return ()
    return tuple(key for key in containers if isinstance(key, str) and key)


def _container_owners(ids: Sequence[str]) -> dict[str, Owner | None]:
    if not ids:
        return {}
    payload = _json(
        _run(("docker", "container", "inspect", *ids)),
        "docker container inspect",
    )
    if not isinstance(payload, list):
        raise HostCheckError("docker container inspect returned invalid JSON")
    result: dict[str, Owner | None] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        identifier = item.get("Id")
        config = item.get("Config")
        labels = config.get("Labels") if isinstance(config, dict) else None
        labels = labels if isinstance(labels, dict) else {}
        lab = labels.get("containerlab")
        topology = labels.get("clab-topo-file")
        if not isinstance(identifier, str):
            continue
        directory = None
        if isinstance(topology, str) and topology:
            directory = Path(topology).resolve().parent
        result[identifier] = Owner(lab, directory) if isinstance(lab, str) and lab else None
    return result


def _network(item: dict[str, Any], owners: dict[str, Owner | None]) -> ObservedNetwork:
    identifier = item.get("Id")
    name = item.get("Name")
    if not isinstance(identifier, str) or not isinstance(name, str):
        raise HostCheckError("docker network inspect returned an invalid network")
    ipam = item.get("IPAM")
    configs = ipam.get("Config") if isinstance(ipam, dict) else None
    subnets: list[Network] = []
    gateways: list[Address] = []
    if isinstance(configs, list):
        for config in configs:
            if not isinstance(config, dict):
                continue
            subnet = config.get("Subnet")
            gateway = config.get("Gateway")
            if isinstance(subnet, str) and subnet:
                try:
                    subnets.append(ipaddress.ip_network(subnet, strict=False))
                except ValueError as error:
                    raise HostCheckError("docker returned an invalid network subnet") from error
            if isinstance(gateway, str) and gateway:
                try:
                    gateways.append(ipaddress.ip_address(gateway))
                except ValueError as error:
                    raise HostCheckError("docker returned an invalid network gateway") from error
    endpoints: dict[Address, Owner | None] = {}
    containers = item.get("Containers")
    if isinstance(containers, dict):
        for container_id, endpoint in containers.items():
            if not isinstance(container_id, str) or not isinstance(endpoint, dict):
                continue
            for field in ("IPv4Address", "IPv6Address"):
                raw = endpoint.get(field)
                if not isinstance(raw, str) or not raw:
                    continue
                try:
                    address = ipaddress.ip_interface(raw).ip
                except ValueError as error:
                    raise HostCheckError("docker returned an invalid endpoint address") from error
                endpoints[address] = owners.get(container_id)
    options = item.get("Options")
    bridge = None
    if isinstance(options, dict):
        value = options.get("com.docker.network.bridge.name")
        if isinstance(value, str) and value:
            bridge = value
    if bridge is None and identifier:
        bridge = f"br-{identifier[:12]}"
    return ObservedNetwork(
        identifier,
        name,
        tuple(subnets),
        tuple(gateways),
        endpoints,
        bridge,
    )


def _routes(version: int) -> tuple[ObservedRoute, ...]:
    family = "-4" if version == 4 else "-6"
    payload = _json(
        _run(("ip", "-json", family, "route", "show", "table", "all")),
        f"ip {family} route",
    )
    if not isinstance(payload, list):
        raise HostCheckError("ip route returned invalid JSON")
    result: list[ObservedRoute] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        destination = item.get("dst")
        if destination in (None, "default"):
            continue
        if not isinstance(destination, str):
            raise HostCheckError("ip route returned an invalid destination")
        try:
            network = ipaddress.ip_network(destination, strict=False)
        except ValueError as error:
            raise HostCheckError("ip route returned an invalid destination") from error
        device = item.get("dev")
        result.append(ObservedRoute(network, device if isinstance(device, str) else None))
    return tuple(result)


def probe_candidate(
    candidate: Network,
    *,
    own_addresses: Iterable[Address] = (),
    timeout: float = 0.1,
    strategy: TraceStrategy | None = None,
) -> bool:
    """Return true when either trace proves the candidate is in use."""
    strategy = strategy if strategy is not None else select_trace_strategy()
    if candidate.prefixlen <= (24 if candidate.version == 4 else 120):
        slots = node_slots(candidate)
        targets = (slots[0], slots[-1])
    else:
        first = int(candidate.network_address)
        last = int(candidate.broadcast_address)
        span = last - first
        if span == 0:
            targets = (candidate.network_address, candidate.network_address)
        elif span == 1:
            targets = (candidate.network_address, candidate.broadcast_address)
        else:
            targets = (
                ipaddress.ip_address(first + max(1, span // 3)),
                ipaddress.ip_address(first + min(span - 1, max(2, (span * 2) // 3))),
            )
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="sticky-ip-trace") as executor:
        outputs = tuple(executor.map(lambda target: strategy.trace(target, timeout), targets))
    allowed = set(own_addresses)
    for output in outputs:
        for address in output:
            if address in candidate and address not in allowed:
                return True
    return False


def _run(arguments: Sequence[str]) -> str:
    try:
        result = subprocess.run(arguments, check=False, capture_output=True, text=True)
    except OSError as error:
        raise HostCheckError(f"could not run {arguments[0]}: {error}") from error
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise HostCheckError(f"{' '.join(arguments[:3])} failed: {detail}")
    return result.stdout


def _json(value: str, operation: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as error:
        raise HostCheckError(f"{operation} returned invalid JSON") from error
