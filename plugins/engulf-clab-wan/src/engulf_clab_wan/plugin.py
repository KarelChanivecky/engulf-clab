from __future__ import annotations

import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from engulf_api import (
    BeforeGoalAPI,
    GoalResult,
    Invocation,
    InvocationAPI,
    StateScope,
    WorkspaceState,
)
from engulf_clab_lab_parser import TOPOLOGY_CONTEXT, TopologySession, editor
from engulf_clab_schema_api import (
    SCHEMA_CONTEXTS,
    LifecycleStage,
    PluginSchema,
    Privilege,
    SchemaBackedPlugin,
    ValueType,
    record_plugin_schema,
)
from engulf_executable_wrapper_api import (
    AfterCallEvent,
    BeforeCallEvent,
    CallContribution,
    CallMode,
    HelpAPI,
    OutcomeKind,
    PreparationFailedEvent,
    PreparedCallEvent,
)

from .errors import WanError
from .logging import use_logger
from .networks import (
    DEFAULT_DNS,
    DEFAULT_GATEWAY,
    DEFAULT_LEASE_TIME,
    DEFAULT_POOL_END,
    DEFAULT_POOL_START,
    DEFAULT_SUBNET,
    cleanup_dhcp_wan_bridges,
    dhcp_wan_bridges,
    release_workspace_bridges,
    setup_dhcp_wan_bridges,
    wan_contract,
)
from .registry import bridge_metadata_for_workspace, workspace_bridge_names
from .topology import load_topology, topology_path_from_args

_INVOCATION_BRIDGES_CONTEXT = "engulf_clab.wan.invocation_bridges"


@dataclass(frozen=True)
class _InvocationBridges:
    """Bridges this invocation newly claimed, and what the workspace held before."""

    retained: tuple[str, ...]
    claimed: tuple[str, ...]


PLUGIN_SCHEMA = (
    PluginSchema("engulf_clab.wan", package="engulf_clab_wan")
    .add_node_prop(
        "labels.ECLAB_DHCP_WAN",
        "Enable a managed IPv4 DHCP and NAT WAN on this bridge node.",
        values=ValueType.BOOLEAN,
    )
    .add_node_prop(
        "labels.ECLAB_DHCP_SUBNET",
        "Set the managed WAN IPv4 subnet.",
        values=ValueType.IPV4_CIDR,
        default="198.19.0.0/24",
    )
    .add_node_prop(
        "labels.ECLAB_DHCP_GATEWAY",
        "Set the managed WAN IPv4 gateway.",
        values=ValueType.IPV4_ADDRESS,
        default="198.19.0.1",
    )
    .add_node_prop(
        "labels.ECLAB_DHCP_POOL_START",
        "Set the first managed WAN DHCP address.",
        values=ValueType.IPV4_ADDRESS,
        default="198.19.0.100",
    )
    .add_node_prop(
        "labels.ECLAB_DHCP_POOL_END",
        "Set the last managed WAN DHCP address.",
        values=ValueType.IPV4_ADDRESS,
        default="198.19.0.200",
    )
    .add_node_prop(
        "labels.ECLAB_DHCP_DNS",
        "Set the managed WAN DHCP DNS address.",
        values=ValueType.IPV4_ADDRESS,
        default="1.1.1.1",
    )
    .add_node_prop(
        "labels.ECLAB_DHCP_LEASE_TIME",
        "Set the DHCP lease duration in seconds.",
        values=ValueType.POSITIVE_INTEGER,
        default=43200,
    )
    .add_runtime_var(
        "ECLAB_UPLINK_IF",
        "Override the host WAN uplink interface; the matching CLI flag takes precedence.",
        values=ValueType.STRING,
    )
    .add_cli_flag(
        "--eclab-uplink-interface",
        "Override the host uplink interface used for WAN NAT.",
        values=ValueType.STRING,
        environment="ECLAB_UPLINK_IF",
    )
    .annotate(
        "labels.ECLAB_DHCP_WAN",
        commands=("deploy", "destroy"),
        lifecycle=(
            LifecycleStage.ANALYZE_CALL,
            LifecycleStage.PREPARE_CALL,
            LifecycleStage.AFTER_CALL,
        ),
        requires=("node.kind is bridge",),
        privilege=Privilege.ROOT,
        host_tools=("ip", "iptables", "sysctl", "sh"),
        implies=("create a managed host bridge, DHCP service, and IPv4 NAT",),
        examples=("ECLAB_DHCP_WAN: 'true'",),
    )
    .annotate(
        "labels.ECLAB_DHCP_SUBNET",
        commands=("deploy",),
        requires=("labels.ECLAB_DHCP_WAN",),
    )
    .annotate(
        "labels.ECLAB_DHCP_GATEWAY",
        commands=("deploy",),
        requires=("labels.ECLAB_DHCP_WAN", "labels.ECLAB_DHCP_SUBNET"),
    )
    .annotate(
        "labels.ECLAB_DHCP_POOL_START",
        commands=("deploy",),
        requires=("labels.ECLAB_DHCP_WAN", "labels.ECLAB_DHCP_POOL_END"),
    )
    .annotate(
        "labels.ECLAB_DHCP_POOL_END",
        commands=("deploy",),
        requires=("labels.ECLAB_DHCP_WAN", "labels.ECLAB_DHCP_POOL_START"),
    )
    .annotate(
        "labels.ECLAB_DHCP_DNS",
        commands=("deploy",),
        requires=("labels.ECLAB_DHCP_WAN",),
    )
    .annotate(
        "labels.ECLAB_DHCP_LEASE_TIME",
        commands=("deploy",),
        requires=("labels.ECLAB_DHCP_WAN",),
    )
    .annotate(
        "ECLAB_UPLINK_IF",
        commands=("deploy",),
        requires=("an existing host egress interface",),
    )
    .annotate(
        "--eclab-uplink-interface",
        commands=("deploy",),
        requires=("an existing host egress interface",),
    )
    .require_host_tool(
        "ip",
        "Create and inspect the managed host bridge.",
        commands=("deploy", "destroy"),
    )
    .require_host_tool(
        "iptables",
        "Create and remove managed IPv4 forwarding and NAT rules.",
        commands=("deploy", "destroy"),
    )
    .require_host_tool(
        "sysctl",
        "Enable and restore shared IPv4 forwarding state.",
        commands=("deploy", "destroy"),
    )
    .require_host_tool(
        "sh", "Launch the packaged Python DHCP service.", commands=("deploy",)
    )
    .require_privilege(
        Privilege.ROOT,
        "Managed bridges, addresses, processes, forwarding, and NAT require root.",
        commands=("deploy", "destroy"),
    )
    .use_case(
        "Provide isolated lab nodes with managed IPv4 DHCP and outbound NAT through a bridge node."
    )
    .reject(
        "Do not apply WAN labels to a non-bridge node or reuse a bridge owned by another workspace."
    )
    .order(
        LifecycleStage.PREPARE_CALL,
        "WAN setup consumes the parsed topology and completes before final topology serialization.",
        after=("engulf_clab.lab_parser",),
        before=("engulf_clab.lab_writer",),
    )
    .route(
        "add-managed-wan",
        "USAGE.md",
        "Read bridge topology, addressing, privileges, ownership, and cleanup.",
    )
    .refer("USAGE.md")
)


def destroy_all_requested(args: tuple[str, ...]) -> bool:
    for argument in args:
        if argument in ("-a", "--all"):
            return True
        if argument.startswith("--all="):
            value = argument.removeprefix("--all=").lower()
            if value not in ("0", "false", "no", "off"):
                return True
    return False


class WanPlugin(SchemaBackedPlugin):
    plugin_id = "engulf_clab.wan"
    schema = PLUGIN_SCHEMA
    priority = 50
    context_reads = (
        frozenset({TOPOLOGY_CONTEXT, _INVOCATION_BRIDGES_CONTEXT}) | SCHEMA_CONTEXTS
    )
    context_writes = frozenset({_INVOCATION_BRIDGES_CONTEXT}) | SCHEMA_CONTEXTS

    def before_goal(
        self, invocation: Invocation, api: BeforeGoalAPI
    ) -> GoalResult[object] | None:
        del invocation
        record_plugin_schema(api, PLUGIN_SCHEMA)
        return None

    def help(self, api: HelpAPI) -> str:
        api.logger.debug("rendering DHCP WAN help")
        contract = wan_contract()
        return (
            "  Bridge-node YAML labels:\n"
            f"    {contract.marker_label}               Enable managed IPv4 DHCP/NAT WAN\n"
            f"    {contract.label('DHCP_SUBNET')}            Subnet (default: {DEFAULT_SUBNET})\n"
            f"    {contract.label('DHCP_GATEWAY')}           Gateway (default: {DEFAULT_GATEWAY})\n"
            f"    {contract.label('DHCP_POOL_START')} / _END  Pool (default: "
            f"{DEFAULT_POOL_START}-{DEFAULT_POOL_END})\n"
            f"    {contract.label('DHCP_DNS')}               DNS (default: {DEFAULT_DNS})\n"
            f"    {contract.label('DHCP_LEASE_TIME')}        Seconds "
            f"(default: {DEFAULT_LEASE_TIME})\n"
            "  Wrapper option:\n"
            "    --eclab-uplink-interface IFACE  Optional host uplink override\n"
            f"  {contract.uplink_environment} is the persistent environment default; "
            "the CLI option wins.\n"
            "  Marked deploys require root; successful destroy releases managed resources."
        )

    def analyze_call(
        self,
        event: BeforeCallEvent,
        api: InvocationAPI,
    ) -> CallContribution | None:
        if event.mode is CallMode.HELP or not event.wrapper_args:
            return None

        command, *rest = event.wrapper_args
        if command == "deploy":
            try:
                topology_path = topology_path_from_args(tuple(rest))
                topology_data = load_topology(topology_path, event.environment)
                dhcp_wan_bridges(topology_data, wan_contract())
            except (WanError, OSError, subprocess.CalledProcessError) as error:
                api.logger.error("%s", error)
                return CallContribution(preempt_exit_code=1)
        return None

    def prepare_call(self, event: PreparedCallEvent, api: InvocationAPI) -> None:
        command, *_ = event.wrapper_args
        if command == "deploy":
            self._setup_before_deploy(api, event.environment)

    def prepare_failed(
        self, event: PreparationFailedEvent, api: InvocationAPI
    ) -> None:
        """Release only the bridges this invocation claimed when preparation unwinds."""
        if not event.wrapper_args or event.wrapper_args[0] != "deploy":
            return
        claimed = api.get_context(_INVOCATION_BRIDGES_CONTEXT)
        if isinstance(claimed, _InvocationBridges):
            with use_logger(api.logger):
                self._rollback_deploy(api, claimed)

    def after_call(self, event: AfterCallEvent, api: InvocationAPI) -> None:
        if event.mode is CallMode.HELP or not event.wrapper_args:
            return
        if event.wrapper_args[0] != "destroy":
            return
        if (
            event.outcome.kind is not OutcomeKind.COMPLETED
            or event.outcome.exit_code != 0
        ):
            return

        args = tuple(event.wrapper_args[1:])
        with use_logger(api.logger):
            if destroy_all_requested(args):
                self._cleanup_all_workspaces(api)
            else:
                workspace = api.state(StateScope.WORKSPACE)
                self._cleanup_workspace(api, workspace)

    def _setup_before_deploy(
        self,
        api: InvocationAPI,
        environment: Mapping[str, str],
    ) -> None:
        try:
            session = api.require_context(TOPOLOGY_CONTEXT)
            if not isinstance(session, TopologySession):
                raise WanError("invalid shared topology session")
            topology_path = session.path
            topology_data = session.original_document()
            contract = wan_contract()
            bridges = dhcp_wan_bridges(topology_data, contract)
            if not bridges:
                return
            workspace = api.state(StateScope.WORKSPACE)
            retained = tuple(workspace_bridge_names(workspace))
            with (
                use_logger(api.logger),
                api.leases(self._bridge_leases(bridge.name for bridge in bridges)),
            ):
                api.logger.info("using topology %s", topology_path)
                try:
                    setup_dhcp_wan_bridges(
                        topology_data,
                        workspace,
                        api.state(StateScope.USER),
                        contract,
                        environment,
                    )
                except BaseException:
                    # Engulf unwinds every plugin before this one, whatever ends
                    # preparation, but never this one: its own partial work is its
                    # own to release. BaseException rather than Exception, so an
                    # interrupt does not strand a live bridge.
                    # setup_dhcp_wan_bridges provisions bridge by bridge, so
                    # record what it did claim before releasing it. The leases are
                    # still held here, so this calls _release_claims and never
                    # _rollback_deploy.
                    self._release_claims(
                        api, self._record_claims(api, workspace, retained)
                    )
                    raise
                self._record_claims(api, workspace, retained)
                mutation = editor(api, self.plugin_id)
                topology = topology_data.get("topology", {})
                nodes = topology.get("nodes", {}) if isinstance(topology, dict) else {}
                for bridge in bridges:
                    labels = (
                        nodes.get(bridge.name, {}).get("labels", {})
                        if isinstance(nodes, dict)
                        else {}
                    )
                    if isinstance(labels, dict):
                        for key in labels:
                            if str(key) in contract.control_labels:
                                mutation.delete(
                                    (
                                        "topology",
                                        "nodes",
                                        bridge.name,
                                        "labels",
                                        str(key),
                                    )
                                )
        except (WanError, OSError, subprocess.CalledProcessError) as error:
            api.logger.error("%s", error)
            raise

    @staticmethod
    def _bridge_leases(names: Iterable[str]) -> tuple[str, ...]:
        bridge_names = tuple(f"wan-bridge:{name}" for name in sorted(set(names)))
        return (*bridge_names, "sysctl:net.ipv4.ip_forward") if bridge_names else ()

    @staticmethod
    def _record_claims(
        api: InvocationAPI,
        workspace: WorkspaceState,
        retained: tuple[str, ...],
    ) -> _InvocationBridges:
        """Publish and return the bridges this invocation added to the retained set."""
        try:
            current = tuple(workspace_bridge_names(workspace))
        except (WanError, OSError) as error:
            # This also runs while a setup failure unwinds. Reporting a metadata
            # read error here would replace the more actionable original cause,
            # and destroy still cleans up from the workspace metadata on disk.
            api.logger.warning("could not record claimed WAN bridges: %s", error)
            return _InvocationBridges(retained=retained, claimed=())
        claimed = tuple(name for name in current if name not in retained)
        recorded = _InvocationBridges(retained=retained, claimed=claimed)
        api.set_context(_INVOCATION_BRIDGES_CONTEXT, recorded)
        # Only preparation unwind reads this record, so a deploy that prepares
        # cleanly would otherwise trip the runtime's unused-context diagnostic.
        api.get_context(_INVOCATION_BRIDGES_CONTEXT)
        return recorded

    def _rollback_deploy(
        self, api: InvocationAPI, claimed: _InvocationBridges
    ) -> None:
        """Release this invocation's bridges while holding no lease yet."""
        if not claimed.claimed:
            return
        with api.leases(self._bridge_leases(claimed.claimed)):
            self._release_claims(api, claimed)

    def _release_claims(
        self, api: InvocationAPI, claimed: _InvocationBridges
    ) -> None:
        """Release this invocation's bridges, leaving a previous deploy's intact.

        The caller must already hold the bridge leases; Engulf rejects nested
        lease acquisition, so this never takes them itself.
        """
        if not claimed.claimed:
            return
        workspace = api.state(StateScope.WORKSPACE)
        try:
            release_workspace_bridges(
                claimed.claimed, workspace, api.state(StateScope.USER)
            )
        finally:
            # Leave the workspace owning exactly what it owned before this
            # invocation; a retry must not see the rolled-back claims.
            bridge_metadata_for_workspace(workspace, list(claimed.retained))
            api.set_context(
                _INVOCATION_BRIDGES_CONTEXT,
                _InvocationBridges(retained=claimed.retained, claimed=()),
            )

    def _cleanup_workspace(self, api: InvocationAPI, workspace: WorkspaceState) -> None:
        names = workspace_bridge_names(workspace)
        with api.leases(self._bridge_leases(names)):
            cleanup_dhcp_wan_bridges(workspace, api.state(StateScope.USER))

    def _cleanup_all_workspaces(self, api: InvocationAPI) -> None:
        workspaces = api.known_workspaces()
        if not workspaces:
            api.logger.info("no managed DHCP WAN workspaces found")
            return

        workspace_names = [
            (workspace, workspace_bridge_names(workspace)) for workspace in workspaces
        ]
        lease_names = self._bridge_leases(
            name for _workspace, names in workspace_names for name in names
        )
        failures: list[str] = []
        with api.leases(lease_names):
            user_state = api.state(StateScope.USER)
            for workspace, _names in workspace_names:
                try:
                    cleanup_dhcp_wan_bridges(workspace, user_state)
                except Exception as error:  # noqa: BLE001 - every workspace must be attempted.
                    failures.append(f"{workspace.root}: {error}")

        if failures:
            raise WanError("DHCP WAN cleanup failed for " + "; ".join(failures))


plugin = WanPlugin()
