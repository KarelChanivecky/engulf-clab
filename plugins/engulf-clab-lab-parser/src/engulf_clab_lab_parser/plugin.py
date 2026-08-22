from __future__ import annotations

from engulf_api import BeforeGoalAPI, GoalResult, Invocation, InvocationAPI
from engulf_clab_schema_api import (
    SCHEMA_CONTEXTS,
    SCHEMA_PLUGIN_DEPENDENCY,
    LifecycleStage,
    PluginSchema,
    record_plugin_schema,
)
from engulf_executable_wrapper_api import (
    AdditionPlacement,
    ArgumentAddition,
    BeforeCallEvent,
    CallContribution,
    CallMode,
    ExecutableWrapperPlugin,
    PreparedCallEvent,
)

from .session import (
    TOPOLOGY_CONTEXT,
    TopologyError,
    TopologySession,
    load_topology,
    topology_path_from_args,
)


class TopologyPlugin(ExecutableWrapperPlugin):
    plugin_id = "engulf_clab.lab_parser"
    priority = 100
    plugin_dependencies = (SCHEMA_PLUGIN_DEPENDENCY,)
    context_reads = SCHEMA_CONTEXTS
    context_writes = frozenset({TOPOLOGY_CONTEXT}) | SCHEMA_CONTEXTS

    def before_goal(
        self, invocation: Invocation, api: BeforeGoalAPI
    ) -> GoalResult[object] | None:
        del invocation
        record_plugin_schema(api, PLUGIN_SCHEMA)
        return None

    def analyze_call(
        self, event: BeforeCallEvent, api: InvocationAPI
    ) -> CallContribution | None:
        if event.mode is CallMode.HELP or not event.wrapper_args:
            return None
        if event.wrapper_args[0] == "destroy":
            return _destroy_topology_contribution(event.wrapper_args)
        if event.wrapper_args[0] != "deploy":
            return None
        try:
            load_topology(topology_path_from_args(tuple(event.wrapper_args[1:])))
        except (TopologyError, OSError) as error:
            api.logger.error("%s", error)
            return CallContribution(preempt_exit_code=1)
        return None

    def prepare_call(self, event: PreparedCallEvent, api: InvocationAPI) -> None:
        if not event.wrapper_args or event.wrapper_args[0] != "deploy":
            return
        path = topology_path_from_args(tuple(event.wrapper_args[1:]))
        api.set_context(TOPOLOGY_CONTEXT, TopologySession(path, load_topology(path)))


def _destroy_topology_contribution(args: tuple[str, ...]) -> CallContribution | None:
    """Select the source explicitly so Containerlab ignores writer residue."""
    if _has_option(args[1:], ("-t", "--topo", "--topology", "--name")):
        return None
    try:
        topology = topology_path_from_args(tuple(args[1:]))
    except TopologyError:
        # Preserve Containerlab's native diagnostics for zero or multiple source
        # topologies. The useful special case is one source plus writer residue.
        return None
    return CallContribution(
        additions=(
            ArgumentAddition(("-t", str(topology)), AdditionPlacement.BEFORE_SEPARATOR),
        ),
    )


def _has_option(args: tuple[str, ...], options: tuple[str, ...]) -> bool:
    return any(
        argument in options
        or any(argument.startswith(f"{option}=") for option in options)
        for argument in args
    )


PLUGIN_SCHEMA = (
    PluginSchema("engulf_clab.lab_parser", package="engulf_clab_lab_parser")
    .use_case(
        "Select and parse one Containerlab topology before topology-aware plugins run."
    )
    .reject("Do not treat generated writer topologies as user-authored source files.")
    .order(
        LifecycleStage.PREPARE_CALL,
        "The parser publishes the mutable topology session before topology mutators consume it.",
        before=("engulf_clab.lab_writer",),
    )
    .route(
        "select-topology", "README.md", "Read topology selection and ambiguity rules."
    )
    .refer("README.md")
    .refer("AGENTS.md")
)
