from __future__ import annotations

from pathlib import Path

from engulf_api import BeforeGoalAPI, GoalResult, Invocation, PluginDependency
from engulf_clab_containers_api import (
    ContainerBuildRecipe,
    ContainerCollectionPlugin,
    ContainerDefinition,
    ContainerImageProvider,
    ContainerNodeRequirements,
    RegisteredContainerCollection,
)
from engulf_clab_schema_api import (
    SCHEMA_CONTEXTS,
    SCHEMA_PLUGIN_DEPENDENCY,
    ExplainedValue,
    LifecycleStage,
    PluginSchema,
    ValueType,
    record_plugin_schema,
)
from engulf_docker_image_api import ImageProviderPlugin

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

WAN_ACCESS = ContainerDefinition(
    name="wan-access",
    summary="NAT one lab interface through eth0, with optional DHCP",
    build=ContainerBuildRecipe(
        dockerfile=_CONTEXT / "containers" / "wan-access" / "Dockerfile",
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

PLUGIN_SCHEMA = (
    PluginSchema("eclab.containers", package="engulf_clab_containers_core")
    .add_node_prop(
        "image",
        "Select an ordinary image reference or one of this collection's packaged helpers.",
        values=(
            ValueType.IMAGE_REFERENCE,
            ExplainedValue(
                "eclab.containers/host-connector",
                "Map lab-facing VIPs to external IPv4 or IPv6 hosts through management networking.",
            ),
            ExplainedValue(
                "eclab.containers/wan-access",
                "Provide outbound IPv4 NAT with optional DHCP on one lab-facing interface.",
            ),
        ),
    )
    .add_node_var(
        "ECLAB_CONNECT_HOST",
        "Map the default lab-facing VIP to a host with VIP;HOST syntax.",
        values=ValueType.STRING,
    )
    .add_node_var(
        "ECLAB_CONNECT_HOST_*",
        "Map the wildcard suffix to another VIP;HOST pair.",
        values=ValueType.STRING,
    )
    .add_node_var(
        "ECLAB_DHCP_SUBNET",
        "Enable DHCP and set the wan-access IPv4 subnet.",
        values=ValueType.IPV4_CIDR,
    )
    .add_node_var(
        "ECLAB_DHCP_GATEWAY", "Set the wan-access DHCP gateway.", values=ValueType.IPV4_ADDRESS
    )
    .add_node_var(
        "ECLAB_DHCP_POOL_START",
        "Set the first wan-access DHCP address.",
        values=ValueType.IPV4_ADDRESS,
    )
    .add_node_var(
        "ECLAB_DHCP_POOL_END",
        "Set the last wan-access DHCP address.",
        values=ValueType.IPV4_ADDRESS,
    )
    .add_node_var(
        "ECLAB_DHCP_DNS", "Set the wan-access DHCP DNS address.", values=ValueType.IPV4_ADDRESS
    )
    .add_node_var(
        "ECLAB_DHCP_LEASE_TIME",
        "Set the wan-access DHCP lease duration in seconds.",
        values=ValueType.POSITIVE_INTEGER,
    )
    .annotate(
        "ECLAB_CONNECT_HOST",
        commands=("deploy",),
        lifecycle=(LifecycleStage.PREPARE_CALL,),
        requires=("node image selects eclab.containers/host-connector",),
        examples=("10.10.10.50;192.0.2.50",),
    )
    .annotate(
        "ECLAB_CONNECT_HOST_*",
        commands=("deploy",),
        lifecycle=(LifecycleStage.PREPARE_CALL,),
        requires=("node image selects eclab.containers/host-connector",),
        examples=("ECLAB_CONNECT_HOST_2=2001:db8:10::50;2001:db8:20::50",),
    )
    .annotate(
        "ECLAB_DHCP_SUBNET",
        commands=("deploy",),
        lifecycle=(LifecycleStage.PREPARE_CALL,),
        requires=("node image selects eclab.containers/wan-access",),
        implies=("DHCP is enabled on the lab-facing interface",),
        examples=("198.19.0.0/24",),
    )
    .annotate(
        "ECLAB_DHCP_GATEWAY",
        commands=("deploy",),
        requires=("node image selects eclab.containers/wan-access",),
    )
    .annotate(
        "ECLAB_DHCP_POOL_START",
        commands=("deploy",),
        requires=("node image selects eclab.containers/wan-access",),
    )
    .annotate(
        "ECLAB_DHCP_POOL_END",
        commands=("deploy",),
        requires=("node image selects eclab.containers/wan-access",),
    )
    .annotate(
        "ECLAB_DHCP_DNS",
        commands=("deploy",),
        requires=("node image selects eclab.containers/wan-access",),
    )
    .annotate(
        "ECLAB_DHCP_LEASE_TIME",
        commands=("deploy",),
        requires=("node image selects eclab.containers/wan-access",),
    )
    .use_case("Use host-connector for explicit VIP mappings or wan-access for outbound access.")
    .reject("Do not use helper-container variables on nodes that select another image.")
    .order(
        LifecycleStage.BEFORE_GOAL,
        "The collection is registered before the container manager resolves packaged image names.",
        before=("engulf_clab.containers",),
    )
    .route(
        "connect-lab-to-host",
        "containers/host-connector/USAGE.md",
        "Read host-connector syntax and routing behavior.",
    )
    .route(
        "provide-lab-wan-access",
        "containers/wan-access/USAGE.md",
        "Read wan-access DHCP and interface conventions.",
    )
    .refer("USAGE.md")
    .refer("containers/host-connector/USAGE.md", title="Host connector node")
    .refer("containers/wan-access/USAGE.md", title="WAN access node")
)


class CoreContainerCollectionPlugin(ContainerCollectionPlugin):
    plugin_dependencies: tuple[PluginDependency, ...] = (
        *ContainerCollectionPlugin.plugin_dependencies,
        SCHEMA_PLUGIN_DEPENDENCY,
    )
    context_reads = ContainerCollectionPlugin.context_reads | SCHEMA_CONTEXTS
    context_writes = ContainerCollectionPlugin.context_writes | SCHEMA_CONTEXTS

    def before_goal(self, invocation: Invocation, api: BeforeGoalAPI) -> GoalResult[object] | None:
        result = super().before_goal(invocation, api)
        record_plugin_schema(api, PLUGIN_SCHEMA)
        return result


_CONTAINERS = (HOST_CONNECTOR, WAN_ACCESS)
plugin = CoreContainerCollectionPlugin("eclab.containers", _CONTAINERS)
image_plugin = ImageProviderPlugin(
    "eclab.containers",
    ContainerImageProvider((RegisteredContainerCollection("eclab.containers", _CONTAINERS),)),
)
