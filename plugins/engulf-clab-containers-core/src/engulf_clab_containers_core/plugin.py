from __future__ import annotations

from pathlib import Path

from engulf_clab_containers_api import (
    ContainerBuildRecipe,
    ContainerCollectionPlugin,
    ContainerDefinition,
    ContainerNodeRequirements,
)

_PACKAGE = Path(__file__).resolve().parent
_CONTEXT = _PACKAGE

HOST_CONNECTOR = ContainerDefinition(
    name="host-connector",
    summary="Map lab-facing VIPs to IPv4 or IPv6 hosts reachable through eth0",
    build=ContainerBuildRecipe(
        dockerfile=_CONTEXT / "containers" / "host-connector" / "Dockerfile",
        context=_CONTEXT,
    ),
    node=ContainerNodeRequirements(
        kind="linux",
        cap_add=("NET_ADMIN",),
        sysctls={
            "net.ipv4.ip_forward": 1,
            "net.ipv4.conf.all.rp_filter": 0,
            "net.ipv4.conf.default.rp_filter": 0,
            "net.ipv6.conf.all.forwarding": 1,
        },
    ),
)

DHCP_WAN_GATEWAY = ContainerDefinition(
    name="dhcp-wan-gateway",
    summary="Serve DHCP on one lab interface, routed out through eth0",
    build=ContainerBuildRecipe(
        dockerfile=_CONTEXT / "containers" / "dhcp-wan-gateway" / "Dockerfile",
        context=_CONTEXT,
    ),
    node=ContainerNodeRequirements(
        kind="linux",
        cap_add=("NET_ADMIN",),
        sysctls={
            "net.ipv4.ip_forward": 1,
        },
    ),
)

plugin = ContainerCollectionPlugin(
    "eclab.containers",
    (HOST_CONNECTOR, DHCP_WAN_GATEWAY),
)
