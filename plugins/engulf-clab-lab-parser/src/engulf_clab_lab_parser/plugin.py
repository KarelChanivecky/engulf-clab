from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from engulf_api import BeforeGoalAPI, GoalResult, Invocation, InvocationAPI
from engulf_clab_schema_api import (
    SCHEMA_CONTEXTS,
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
    WRITER_TEMP_PREFIX,
    TopologyError,
    TopologySession,
    derived_topology_path,
    is_topology_mutation_command,
    load_topology,
    topology_path_from_args,
)

# Containerlab subcommands that resolve a lab by globbing the working directory
# for a topology when -t is absent. `exec` and `events` are deliberately absent:
# without a topology they act on every lab on the host rather than globbing, so
# naming one would narrow what the user asked for. A single-source `redeploy`
# uses the same parse/mutate/write pipeline as `deploy`.
_LAB_COMMANDS = frozenset({"graph", "inspect", "save"})


class TopologyPlugin(ExecutableWrapperPlugin):
    plugin_id = "engulf_clab.lab_parser"
    priority = 100
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
            return _destroy_topology_contribution(
                event.wrapper_args, event.environment
            )
        if event.wrapper_args[0] in _LAB_COMMANDS:
            return _lab_topology_contribution(event.wrapper_args)
        if not is_topology_mutation_command(event.wrapper_args):
            return None
        try:
            load_topology(
                topology_path_from_args(tuple(event.wrapper_args[1:])),
                event.environment,
            )
        except (TopologyError, OSError) as error:
            api.logger.error("%s", error)
            return CallContribution(preempt_exit_code=1)
        return None

    def prepare_call(self, event: PreparedCallEvent, api: InvocationAPI) -> None:
        if not is_topology_mutation_command(event.wrapper_args):
            return
        path = topology_path_from_args(tuple(event.wrapper_args[1:]))
        api.set_context(
            TOPOLOGY_CONTEXT,
            TopologySession(path, load_topology(path, event.environment)),
        )


def _lab_topology_contribution(args: tuple[str, ...]) -> CallContribution | None:
    """Name the deployed topology for a command that otherwise globs for one.

    Containerlab searches the working directory when -t is absent, and the
    derived topology the writer retains until destroy makes that search
    ambiguous: the lab cannot be inspected, graphed, or saved from its own
    directory any more. Point these commands at the retained topology, which is
    also the file the running containers are labelled with. A command that
    already selects its lab by name or --all is left alone. An explicit source
    topology is replaced only when its retained deploy topology exists; an
    explicit retained topology is therefore also left alone.
    """
    rest = tuple(args[1:])
    if _has_option(rest, ("--name", "-a", "--all")):
        return None
    try:
        topology = topology_path_from_args(rest)
    except TopologyError:
        # Preserve Containerlab's native diagnostics for zero or multiple source
        # topologies. The useful special case is one source plus writer residue.
        return None
    retained = derived_topology_path(topology)
    target = retained if retained.is_file() else topology
    explicit = _has_option(rest, ("-t", "--topo", "--topology"))
    if explicit and target == topology:
        return None
    return CallContribution(
        removals=frozenset(_topology_indexes(args)) if explicit else frozenset(),
        additions=(
            ArgumentAddition(("-t", str(target)), AdditionPlacement.BEFORE_SEPARATOR),
        ),
    )


def _destroy_topology_contribution(
    args: tuple[str, ...], environment: Mapping[str, str]
) -> CallContribution | None:
    """Route destroy through the retained topology used for deploy when present."""
    rest = tuple(args[1:])
    if _has_option(rest, ("-a", "--all")):
        return None
    name = _option_value(rest, "--name")
    if name is not None:
        matches = []
        for candidate in Path.cwd().glob(f"{WRITER_TEMP_PREFIX}*.clab.yml"):
            try:
                document = load_topology(candidate, environment)
            except TopologyError:
                continue
            if document.get("name") == name:
                matches.append(candidate.resolve())
        if len(matches) != 1:
            return None
        return CallContribution(
            removals=frozenset(_option_indexes(args, "--name")),
            additions=(
                ArgumentAddition(
                    ("-t", str(matches[0])), AdditionPlacement.BEFORE_SEPARATOR
                ),
            ),
        )
    try:
        topology = topology_path_from_args(rest)
    except TopologyError:
        # Preserve Containerlab's native diagnostics for zero or multiple source
        # topologies. The useful special case is one source plus writer residue.
        return None
    retained = derived_topology_path(topology)
    target = retained if retained.is_file() else topology
    explicit = _has_option(rest, ("-t", "--topo", "--topology"))
    if explicit and target == topology:
        return None
    removals = frozenset(_topology_indexes(args)) if explicit else frozenset()
    return CallContribution(
        removals=removals,
        additions=(
            ArgumentAddition(("-t", str(target)), AdditionPlacement.BEFORE_SEPARATOR),
        ),
    )


def _topology_indexes(args: tuple[str, ...]) -> set[int]:
    indexes: set[int] = set()
    for index, value in enumerate(args):
        if value in {"-t", "--topo", "--topology"}:
            indexes.update((index, index + 1))
        elif any(
            value.startswith(prefix)
            for prefix in ("-t=", "--topo=", "--topology=")
        ):
            indexes.add(index)
    return {index for index in indexes if index < len(args)}


def _option_indexes(args: tuple[str, ...], option: str) -> set[int]:
    indexes: set[int] = set()
    for index, value in enumerate(args):
        if value == option:
            indexes.update((index, index + 1))
        elif value.startswith(f"{option}="):
            indexes.add(index)
    return {index for index in indexes if index < len(args)}


def _option_value(args: tuple[str, ...], option: str) -> str | None:
    for index, value in enumerate(args):
        if value == option and index + 1 < len(args):
            return args[index + 1]
        if value.startswith(f"{option}="):
            return value.removeprefix(f"{option}=")
    return None


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
        "select-topology", "USAGE.md", "Read topology selection and ambiguity rules."
    )
    .route(
        "lab-env-file",
        "USAGE.md",
        "Read how a lab's private <name>.env resolves topology expressions.",
    )
    .refer("USAGE.md")
)
