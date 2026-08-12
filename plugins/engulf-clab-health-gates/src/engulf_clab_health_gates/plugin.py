"""Engulf adapter that invokes health gates after deploy."""

from __future__ import annotations

from engulf_api import DependencyPosition, InvocationAPI, PluginDependency
from engulf_clab_lab_parser import TOPOLOGY_CONTEXT, TopologySession
from engulf_executable_wrapper_api import (
    AfterCallEvent,
    BeforeCallEvent,
    CallContribution,
    CallMode,
    ExecutableWrapperPlugin,
    HelpAPI,
    OutcomeKind,
)

from .health import HealthGateError, gates_from_topology, wait_for_gates

HEALTH_GATES_PLUGIN_ID = "engulf_clab.health_gates"


class HealthGatesPlugin(ExecutableWrapperPlugin):
    plugin_id = HEALTH_GATES_PLUGIN_ID
    priority = -90
    plugin_dependencies = (
        PluginDependency(
            "engulf_clab.lab_parser",
            preprocess=DependencyPosition.BEFORE,
            postprocess=None,
        ),
    )
    context_reads = frozenset({TOPOLOGY_CONTEXT})

    def help(self, api: HelpAPI) -> str:
        api.logger.debug("rendering health-gates help")
        return "  x-engulf-clab-health-gates  Wait for selected nodes after deploy"

    def analyze_call(
        self, event: BeforeCallEvent, api: InvocationAPI
    ) -> CallContribution | None:
        return None

    def after_call(self, event: AfterCallEvent, api: InvocationAPI) -> None:
        if (
            event.mode is CallMode.HELP
            or not event.wrapper_args
            or event.wrapper_args[0] != "deploy"
            or event.outcome.kind is not OutcomeKind.COMPLETED
            or event.outcome.exit_code != 0
        ):
            return
        session = api.require_context(TOPOLOGY_CONTEXT)
        if not isinstance(session, TopologySession):
            raise HealthGateError("invalid shared topology session")
        gates = gates_from_topology(session.original_document(), session.path)
        wait_for_gates(gates, info=api.logger.info)


plugin = HealthGatesPlugin()
