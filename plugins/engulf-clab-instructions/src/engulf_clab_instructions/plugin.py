from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from engulf_api import (
    AfterGoalAPI,
    BeforeGoalAPI,
    GoalResult,
    GoalResultStatus,
    Invocation,
    InvocationAPI,
)
from engulf_clab_instructions_api import (
    INSTRUCTION_CONTEXTS,
    DeploymentInstruction,
    instructions,
)
from engulf_clab_lab_parser import (
    TOPOLOGY_CONTEXT,
    TopologySession,
    editor,
    effective_nodes,
)
from engulf_clab_schema_api import (
    SCHEMA_CONTEXTS,
    LifecycleStage,
    PluginSchema,
    SchemaBackedPlugin,
    ValueType,
    record_plugin_schema,
)
from engulf_executable_wrapper_api import (
    BeforeCallEvent,
    CallContribution,
    HelpAPI,
    PreparedCallEvent,
)

PLUGIN_ID = "engulf_clab.instructions"
ECLAB_INSTRUCTIONS = "ECLAB_INSTRUCTIONS"
_PLAN_CONTEXT = f"{PLUGIN_ID}.plan"
_ENV_PREFIX = re.compile(r"[^A-Z0-9]+")

PLUGIN_SCHEMA = (
    PluginSchema(PLUGIN_ID, package="engulf_clab_instructions")
    .add_runtime_var(
        ECLAB_INSTRUCTIONS,
        "Set a process-wide message used for nodes without a topology instruction value.",
        values=ValueType.STRING,
    )
    .add_node_var(
        ECLAB_INSTRUCTIONS,
        "Set a topology-wide or node-specific post-deployment message; node values override inherited values.",
        values=ValueType.STRING,
    )
    .annotate(
        ECLAB_INSTRUCTIONS,
        commands=("deploy", "redeploy"),
        lifecycle=(LifecycleStage.PREPARE_CALL, LifecycleStage.AFTER_GOAL),
        implies=(
            "remove topology declarations from the generated deploy topology",
            "show the effective message only after a successful deployment",
        ),
    )
    .use_case("Show operator follow-up commands, service URLs, or free-form deployment notes.")
    .order(
        LifecycleStage.BEFORE_GOAL,
        "Register the plugin declaration before the runtime schema collector snapshots active providers.",
        before=("engulf_clab.schema",),
    )
    .order(
        LifecycleStage.PREPARE_CALL,
        "Read and remove the instruction control after topology parsing and before serialization.",
        after=("engulf_clab.lab_parser",),
        before=("engulf_clab.lab_writer",),
    )
    .refer("USAGE.md")
)


class InstructionsPlugin(SchemaBackedPlugin):
    """Render topology and plugin contributions after successful deploys."""

    plugin_id = PLUGIN_ID
    schema = PLUGIN_SCHEMA
    context_reads = (
        SCHEMA_CONTEXTS
        | INSTRUCTION_CONTEXTS
        | frozenset({TOPOLOGY_CONTEXT, _PLAN_CONTEXT})
    )
    context_writes = SCHEMA_CONTEXTS | frozenset({_PLAN_CONTEXT})

    def before_goal(
        self, invocation: Invocation, api: BeforeGoalAPI
    ) -> GoalResult[object] | None:
        del invocation
        record_plugin_schema(api, PLUGIN_SCHEMA)
        return None

    def help(self, api: HelpAPI) -> str:
        environment_name = _environment_name(
            api.application.short_product_name or api.application.product
        )
        return (
            f"  topology.defaults.env.{environment_name}\n"
            f"  topology.kinds.<kind>.env.{environment_name}\n"
            f"  topology.groups.<group>.env.{environment_name}\n"
            f"  topology.nodes.<node>.env.{environment_name}\n"
            f"  {environment_name}=...  Set a process-wide fallback message\n"
            "  Plugin API: engulf-clab-instructions-api"
        )

    def analyze_call(
        self, event: BeforeCallEvent, api: InvocationAPI
    ) -> CallContribution | None:
        del event, api
        return None

    def prepare_call(self, event: PreparedCallEvent, api: InvocationAPI) -> None:
        if not event.wrapper_args or event.wrapper_args[0] not in {"deploy", "redeploy"}:
            return

        environment_name = _environment_name(
            api.application.short_product_name or api.application.product
        )
        session = api.get_context(TOPOLOGY_CONTEXT)
        if isinstance(session, TopologySession):
            document = session.materialize()
            entries = _topology_instructions(
                document,
                environment_name,
                event.environment.get(environment_name),
            )
            _remove_topology_controls(document, environment_name, api)
        else:
            entries = _global_instructions(event.environment.get(environment_name))

        api.set_context(_PLAN_CONTEXT, entries, allow_unused=True)

    def after_goal(
        self,
        invocation: Invocation,
        result: GoalResult[object],
        api: AfterGoalAPI,
    ) -> GoalResult[object]:
        # Read both shared registries on every invocation so a contributor can
        # safely publish before a command that later fails or is not a deploy.
        entries = api.get_context(_PLAN_CONTEXT, ())
        contributions = instructions(api)
        if (
            result.status is not GoalResultStatus.COMPLETED
            or result.exit_code != 0
            or not invocation.arguments
            or invocation.arguments[0] not in {"deploy", "redeploy"}
        ):
            return result
        if type(entries) is not tuple or any(
            not isinstance(item, DeploymentInstruction) for item in entries
        ):
            raise RuntimeError("invalid prepared deployment instruction plan")
        combined = _deduplicate((*entries, *contributions))
        if combined:
            api.logger.info("%s", _format_instructions(combined))
        return result


def _environment_name(product_name: str) -> str:
    prefix = _ENV_PREFIX.sub("_", product_name.upper()).strip("_")
    if not prefix:
        raise ValueError("application product metadata cannot form an environment prefix")
    return f"{prefix}_INSTRUCTIONS"


def _global_instructions(value: str | None) -> tuple[DeploymentInstruction, ...]:
    if value is None or not value.strip():
        return ()
    return (DeploymentInstruction(title="Global instructions", text=value),)


def _topology_instructions(
    document: Mapping[str, Any],
    environment_name: str,
    global_environment: str | None,
) -> tuple[DeploymentInstruction, ...]:
    topology = document.get("topology")
    if not isinstance(topology, Mapping):
        return _global_instructions(global_environment)

    entries: list[DeploymentInstruction] = []
    global_values: list[str] = []
    nodes = effective_nodes(document)
    for node in nodes:
        environment = node.data.get("env", {})
        value = environment.get(environment_name) if isinstance(environment, Mapping) else None
        origin = node.origin("env", environment_name)
        if value is not None:
            if not isinstance(value, str):
                raise TypeError(f"{environment_name} must resolve to a string")
            if not value.strip():
                continue
            if origin is not None and origin.level == "defaults":
                if value not in global_values:
                    global_values.append(value)
            else:
                entries.append(
                    DeploymentInstruction(
                        title="Node instructions",
                        text=value,
                        node=node.name,
                    )
                )
        elif global_environment is not None and global_environment.strip():
            if global_environment not in global_values:
                global_values.append(global_environment)

    if not nodes:
        defaults = topology.get("defaults")
        default_environment = defaults.get("env", {}) if isinstance(defaults, Mapping) else {}
        if (
            isinstance(default_environment, Mapping)
            and environment_name in default_environment
        ):
            default_value = default_environment[environment_name]
            if isinstance(default_value, str) and default_value.strip():
                global_values.append(default_value)
        elif global_environment is not None and global_environment.strip():
            global_values.append(global_environment)

    entries[0:0] = [
        DeploymentInstruction(title="Global instructions", text=value)
        for value in global_values
    ]
    return tuple(entries)


def _remove_topology_controls(
    document: Mapping[str, Any],
    environment_name: str,
    api: InvocationAPI,
) -> None:
    topology = document.get("topology")
    if not isinstance(topology, Mapping):
        return
    mutation = editor(api, PLUGIN_ID)
    for section in ("defaults", "kinds", "groups", "nodes"):
        declarations = topology.get(section)
        if not isinstance(declarations, Mapping):
            continue
        if section == "defaults":
            candidates: tuple[tuple[str | int | None, object], ...] = (
                (None, declarations),
            )
        else:
            candidates = tuple(
                (name, item) for name, item in declarations.items()
            )
        for name, declaration in candidates:
            if not isinstance(declaration, Mapping):
                continue
            environment = declaration.get("env")
            if not isinstance(environment, Mapping) or environment_name not in environment:
                continue
            path: tuple[str | int, ...]
            if name is None:
                path = ("topology", section, "env", environment_name)
            else:
                path = ("topology", section, name, "env", environment_name)
            mutation.delete(path)


def _deduplicate(
    entries: tuple[DeploymentInstruction, ...],
) -> tuple[DeploymentInstruction, ...]:
    result: list[DeploymentInstruction] = []
    for entry in entries:
        if entry not in result:
            result.append(entry)
    return tuple(result)


def _format_instructions(entries: tuple[DeploymentInstruction, ...]) -> str:
    lines = ["Post-deployment instructions:"]
    for entry in entries:
        title = entry.title
        if entry.node is not None:
            title = f"{title} ({entry.node})"
        lines.extend(("", f"{title}:"))
        if entry.text:
            lines.extend(f"  {line}" for line in entry.text.splitlines())
        if entry.commands:
            lines.append("  Commands:")
            lines.extend(f"    $ {command}" for command in entry.commands)
        if entry.urls:
            lines.append("  Web pages:")
            lines.extend(f"    {url}" for url in entry.urls)
    return "\n".join(lines)
