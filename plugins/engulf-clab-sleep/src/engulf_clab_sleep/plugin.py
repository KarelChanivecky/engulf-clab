from __future__ import annotations

from engulf_api import BeforeGoalAPI, GoalResult, Invocation
from engulf_clab_lab_registry_api import (
    LAB_REGISTRY_CONTEXT,
    LabRegistryError,
    lab_registry,
)
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

from .command import SleepError, execute, parse_options, plan
from .docker import DockerClient, DockerError

PLUGIN_SCHEMA = (
    PluginSchema("engulf_clab.sleep", package="engulf_clab_sleep")
    .add_command(
        "sleep",
        "Remove lab containers and reclaim lab-owned Docker image storage.",
    )
    .add_cli_flag(
        ("-t", "--topology"),
        "Select one lab topology instead of discovering it in the current directory.",
        command="sleep",
        values=ValueType.FILE_PATH,
    )
    .add_cli_flag(
        "--all",
        "Sleep every known lab only when every lab is already destroyed.",
        command="sleep",
    )
    .add_cli_flag(
        "--stopped",
        "With --all, sleep only labs whose containers exist but are stopped.",
        command="sleep",
    )
    .annotate(
        "sleep",
        lifecycle=(LifecycleStage.BEFORE_GOAL,),
        implies=(
            "normal Containerlab execution is preempted",
            "lab containers, writable layers, anonymous volumes, and selected images are deleted",
            "lab directories and registry records are preserved",
        ),
        host_tools=("docker",),
        privilege=Privilege.CONTAINER_RUNTIME,
        examples=(
            "eclab sleep -t lab.clab.yml",
            "eclab sleep --all",
            "eclab sleep --all --stopped",
        ),
    )
    .annotate(
        "-t",
        commands=("sleep",),
        path_base=PathBase.INVOCATION_DIRECTORY,
        conflicts_with=("--all",),
    )
    .annotate(
        "--all",
        commands=("sleep",),
        conflicts_with=("-t or --topology",),
        implies=("the command fails if any known lab still has containers",),
    )
    .annotate(
        "--stopped",
        commands=("sleep",),
        requires=("--all",),
        implies=("running and destroyed labs are not selected",),
    )
    .require_host_tool(
        "docker",
        "Docker supplies lab discovery and removes containers, volumes, and images.",
        commands=("sleep",),
    )
    .use_case("Reclaim Docker storage while preserving a lab's source workspace.")
    .reject("Do not use --all when any known lab must remain deployed.")
    .route(
        "reclaim-lab-docker-storage",
        "USAGE.md",
        "Read deletion scope, shared-image behavior, safety, and failure recovery.",
    )
    .refer("USAGE.md")
)


class SleepPlugin(SchemaBackedPlugin):
    """Own the destructive Docker-only sleep command."""

    plugin_id = "engulf_clab.sleep"
    schema = PLUGIN_SCHEMA
    priority = 195
    context_reads = SCHEMA_CONTEXTS | frozenset({LAB_REGISTRY_CONTEXT})
    context_writes = SCHEMA_CONTEXTS

    def before_goal(
        self, invocation: Invocation, api: BeforeGoalAPI
    ) -> GoalResult[object] | None:
        record_plugin_schema(api, PLUGIN_SCHEMA)
        if not invocation.arguments or invocation.arguments[0] != "sleep":
            return None
        application_name = api.application.short_product_name or api.application.product
        arguments = invocation.arguments[1:]
        options = parse_options(arguments, f"{application_name} sleep")
        registry = lab_registry(api)
        docker = DockerClient()
        with api.leases(("eclab-sleep:docker",)):
            try:
                sleep_plan = plan(
                    arguments,
                    cwd=invocation.cwd,
                    environment=invocation.environment,
                    registry=registry,
                    docker=docker,
                    program=f"{application_name} sleep",
                    options=options,
                )
            except (DockerError, SleepError, LabRegistryError) as error:
                api.logger.error("%s sleep: %s", application_name, error)
                return GoalResult.completed(exit_code=1)
            exit_code = execute(
                sleep_plan,
                registry=registry,
                docker=docker,
                logger=api.logger,
            )
        return GoalResult.completed(exit_code=exit_code)

    def help(self, api: HelpAPI) -> str:
        del api
        return (
            "  sleep [-t TOPOLOGY | --all [--stopped]]  "
            "Remove lab containers and reclaim lab-owned Docker images"
        )
