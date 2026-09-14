from __future__ import annotations

from engulf_api import BeforeGoalAPI, GoalResult, Invocation
from engulf_clab_lab_registry_api import LAB_REGISTRY_CONTEXT, lab_registry
from engulf_clab_schema_api import (
    SCHEMA_CONTEXTS,
    LifecycleStage,
    PathBase,
    PluginSchema,
    Privilege,
    SchemaBackedPlugin,
    ValueType,
    record_plugin_schema,
)
from engulf_executable_wrapper_api import HelpAPI

from .command import main as run_consumption

PLUGIN_SCHEMA = (
    PluginSchema("engulf_clab.consumption", package="engulf_clab_consumption")
    .add_command(
        "consumption", "Report CPU, RAM, lab-directory, and image consumption."
    )
    .add_cli_flag(
        ("-t", "--topology"),
        "Select one lab topology instead of discovering it in the current directory.",
        command="consumption",
        values=ValueType.FILE_PATH,
    )
    .add_cli_flag(
        "--all",
        "Report every deployed or indexed Containerlab lab.",
        command="consumption",
    )
    .add_cli_flag(
        ("-p", "--poll"),
        "Refresh consumption every two seconds until interrupted.",
        command="consumption",
    )
    .annotate(
        "consumption",
        lifecycle=(LifecycleStage.BEFORE_GOAL,),
        implies=(
            "normal Containerlab execution is preempted",
            "explicit queries contribute observations to the shared lab registry",
        ),
        host_tools=("docker",),
        privilege=Privilege.CONTAINER_RUNTIME,
        examples=("eclab consumption --all -p",),
    )
    .annotate(
        "-t",
        commands=("consumption",),
        path_base=PathBase.INVOCATION_DIRECTORY,
        conflicts_with=("--all",),
    )
    .annotate(
        "--all",
        commands=("consumption",),
        conflicts_with=("-t or --topology",),
    )
    .annotate(
        "-p",
        commands=("consumption",),
        implies=("measurements refresh every two seconds",),
    )
    .require_host_tool(
        "docker",
        "Docker supplies lab discovery, container statistics, and image storage accounting.",
        commands=("consumption",),
    )
    .use_case("Compare deployed, stopped, and reclaimed labs.")
    .route(
        "inspect-resource-consumption",
        "USAGE.md",
        "Read selection, measurement, storage accounting, polling, and limitations.",
    )
    .refer("USAGE.md")
)


class ConsumptionPlugin(SchemaBackedPlugin):
    """Own consumption measurement and reporting."""

    plugin_id = "engulf_clab.consumption"
    schema = PLUGIN_SCHEMA
    priority = 200
    context_reads = SCHEMA_CONTEXTS | frozenset({LAB_REGISTRY_CONTEXT})
    context_writes = SCHEMA_CONTEXTS

    def before_goal(
        self, invocation: Invocation, api: BeforeGoalAPI
    ) -> GoalResult[object] | None:
        record_plugin_schema(api, PLUGIN_SCHEMA)
        if not invocation.arguments or invocation.arguments[0] != "consumption":
            return None
        application_name = api.application.short_product_name or api.application.product
        exit_code = run_consumption(
            invocation.arguments[1:],
            cwd=invocation.cwd,
            environment=invocation.environment,
            program=f"{application_name} consumption",
            logger=api.logger,
            registry=lab_registry(api),
        )
        return GoalResult.completed(exit_code=exit_code)

    def help(self, api: HelpAPI) -> str:
        del api
        return (
            "  consumption [-t TOPOLOGY | --all] [-p]  "
            "Report state, CPU, RAM, lab-directory, and unique/shared image storage"
        )
