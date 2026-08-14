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

LDAP_389DS = ContainerDefinition(
    name="ldap-389ds",
    summary="389 Directory Server with a Cockpit management UI for lab authentication",
    build=ContainerBuildRecipe(
        dockerfile=_CONTEXT / "containers" / "ldap-389ds" / "Dockerfile",
        context=_CONTEXT,
    ),
    node=ContainerNodeRequirements(kind="linux"),
)

PROXY_NODE = ContainerDefinition(
    name="proxy-node",
    summary="Browser-access Squid and Dante proxies with a small control UI",
    build=ContainerBuildRecipe(
        dockerfile=_CONTEXT / "containers" / "proxy-node" / "Dockerfile",
        context=_CONTEXT,
    ),
    node=ContainerNodeRequirements(kind="linux"),
)

UBUNTU_FIREFOX_GUI = ContainerDefinition(
    name="ubuntu-firefox-gui",
    summary="Interactive Firefox desktop client served over noVNC",
    build=ContainerBuildRecipe(
        dockerfile=_CONTEXT / "containers" / "ubuntu-firefox-gui" / "Dockerfile",
        context=_CONTEXT,
    ),
    node=ContainerNodeRequirements(kind="linux"),
)

plugin = ContainerCollectionPlugin(
    "eclab.containers",
    (HOST_CONNECTOR, LDAP_389DS, PROXY_NODE, UBUNTU_FIREFOX_GUI),
)
