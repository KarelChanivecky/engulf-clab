from __future__ import annotations

import subprocess
from collections.abc import Iterable

from engulf_api import DependencyPosition, InvocationAPI, PluginDependency, StateScope, WorkspaceState
from engulf_clab_lab_parser import TOPOLOGY_CONTEXT, TopologySession, editor
from engulf_executable_wrapper_api import (
    AfterCallEvent,
    BeforeCallEvent,
    CallContribution,
    CallMode,
    ExecutableWrapperPlugin,
    HelpAPI,
    OutcomeKind,
    PreparedCallEvent,
)

from .errors import WanError
from .logging import use_logger
from .networks import cleanup_dhcp_wan_bridges, dhcp_wan_bridges, setup_dhcp_wan_bridges
from .registry import workspace_bridge_names
from .topology import load_topology, topology_path_from_args


def destroy_all_requested(args: tuple[str, ...]) -> bool:
    for argument in args:
        if argument in ("-a", "--all"):
            return True
        if argument.startswith("--all="):
            value = argument.removeprefix("--all=").lower()
            if value not in ("0", "false", "no", "off"):
                return True
    return False


class WanPlugin(ExecutableWrapperPlugin):
    plugin_id = "engulf_clab.wan"
    priority = 50
    plugin_dependencies = (
        PluginDependency("engulf_clab.lab_parser", preprocess=DependencyPosition.BEFORE, postprocess=None),
        PluginDependency("engulf_clab.lab_writer", preprocess=DependencyPosition.AFTER, postprocess=None),
    )
    context_reads = frozenset({TOPOLOGY_CONTEXT})

    def help(self, api: HelpAPI) -> str:
        api.logger.debug("rendering DHCP WAN help")
        return (
            "  FCLAB_DHCP_WAN   Manage labeled bridge nodes as DHCP/NAT WANs\n"
            "                    before deploy and after successful destroy"
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
                topology_data = load_topology(topology_path)
                dhcp_wan_bridges(topology_data)
            except (WanError, OSError, subprocess.CalledProcessError) as error:
                api.logger.error("%s", error)
                return CallContribution(preempt_exit_code=1)
        return None

    def prepare_call(self, event: PreparedCallEvent, api: InvocationAPI) -> None:
        command, *rest = event.wrapper_args
        if command == "deploy":
            self._setup_before_deploy(tuple(rest), api)

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

    def _setup_before_deploy(self, args: tuple[str, ...], api: InvocationAPI) -> None:
        try:
            topology_path = topology_path_from_args(args)
            session = api.require_context(TOPOLOGY_CONTEXT)
            if not isinstance(session, TopologySession):
                raise WanError("invalid shared topology session")
            topology_data = session.original_document()
            bridges = dhcp_wan_bridges(topology_data)
            if not bridges:
                return
            with (
                use_logger(api.logger),
                api.leases(self._bridge_leases(bridge.name for bridge in bridges)),
            ):
                api.logger.info("using topology %s", topology_path)
                setup_dhcp_wan_bridges(
                    topology_data,
                    api.state(StateScope.WORKSPACE),
                    api.state(StateScope.USER),
                )
                mutation = editor(api, self.plugin_id)
                topology = topology_data.get("topology", {})
                nodes = topology.get("nodes", {}) if isinstance(topology, dict) else {}
                for bridge in bridges:
                    labels = nodes.get(bridge.name, {}).get("labels", {}) if isinstance(nodes, dict) else {}
                    if isinstance(labels, dict):
                        for key in labels:
                            if str(key).startswith("FCLAB_DHCP_"):
                                mutation.delete(("topology", "nodes", bridge.name, "labels", str(key)))
        except (WanError, OSError, subprocess.CalledProcessError) as error:
            api.logger.error("%s", error)
            raise

    @staticmethod
    def _bridge_leases(names: Iterable[str]) -> tuple[str, ...]:
        bridge_names = tuple(f"wan-bridge:{name}" for name in sorted(set(names)))
        return (*bridge_names, "sysctl:net.ipv4.ip_forward") if bridge_names else ()

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
