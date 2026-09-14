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

from .command import ReclaimStorageError, execute, parse_options, plan
from .docker import DockerClient, DockerError

PLUGIN_SCHEMA = (
    PluginSchema("engulf_clab.reclaim_storage", package="engulf_clab_reclaim_storage")
    .add_command(
        "reclaim-storage",
        "Remove lab containers and reclaim lab-owned Docker image storage.",
    )
    .add_cli_flag(
        ("-t", "--topology"),
        "Select one lab topology instead of discovering it in the current directory.",
        command="reclaim-storage",
        values=ValueType.FILE_PATH,
    )
    .add_cli_flag(
        "--all",
        "Reclaim storage for every known lab only when all are already destroyed.",
        command="reclaim-storage",
    )
    .add_cli_flag(
        "--stopped",
        "With --all, reclaim only labs whose containers exist but are stopped.",
        command="reclaim-storage",
    )
    .annotate(
        "reclaim-storage",
        lifecycle=(LifecycleStage.BEFORE_GOAL,),
        implies=(
            "normal Containerlab execution is preempted",
            "lab containers, writable layers, anonymous volumes, and selected images are deleted",
            "lab directories and registry records are preserved",
            "Docker-reported storage saved is measured and logged",
        ),
        host_tools=("docker",),
        privilege=Privilege.CONTAINER_RUNTIME,
        examples=(
            "eclab reclaim-storage -t lab.clab.yml",
            "eclab reclaim-storage --all",
            "eclab reclaim-storage --all --stopped",
        ),
    )
    .annotate(
        "-t",
        commands=("reclaim-storage",),
        path_base=PathBase.INVOCATION_DIRECTORY,
        conflicts_with=("--all",),
    )
    .annotate(
        "--all",
        commands=("reclaim-storage",),
        conflicts_with=("-t or --topology",),
        implies=("the command fails if any known lab still has containers",),
    )
    .annotate(
        "--stopped",
        commands=("reclaim-storage",),
        requires=("--all",),
        implies=("running and destroyed labs are not selected",),
    )
    .require_host_tool(
        "docker",
        "Docker supplies lab discovery and removes containers, volumes, and images.",
        commands=("reclaim-storage",),
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


class ReclaimStoragePlugin(SchemaBackedPlugin):
    """Own the destructive Docker-only storage-reclamation command."""

    plugin_id = "engulf_clab.reclaim_storage"
    schema = PLUGIN_SCHEMA
    priority = 195
    context_reads = SCHEMA_CONTEXTS | frozenset({LAB_REGISTRY_CONTEXT})
    context_writes = SCHEMA_CONTEXTS

    def before_goal(
        self, invocation: Invocation, api: BeforeGoalAPI
    ) -> GoalResult[object] | None:
        record_plugin_schema(api, PLUGIN_SCHEMA)
        if not invocation.arguments or invocation.arguments[0] != "reclaim-storage":
            return None
        application_name = api.application.short_product_name or api.application.product
        arguments = invocation.arguments[1:]
        options = parse_options(arguments, f"{application_name} reclaim-storage")
        registry = lab_registry(api)
        docker = DockerClient()
        with api.leases(("eclab-reclaim-storage:docker",)):
            try:
                reclaim_plan = plan(
                    arguments,
                    cwd=invocation.cwd,
                    environment=invocation.environment,
                    registry=registry,
                    docker=docker,
                    program=f"{application_name} reclaim-storage",
                    options=options,
                )
            except (DockerError, ReclaimStorageError, LabRegistryError) as error:
                api.logger.error("%s reclaim-storage: %s", application_name, error)
                return GoalResult.completed(exit_code=1)
            exit_code = execute(
                reclaim_plan,
                registry=registry,
                docker=docker,
                logger=api.logger,
            )
        return GoalResult.completed(exit_code=exit_code)

    def help(self, api: HelpAPI) -> str:
        del api
        return (
            "  reclaim-storage [-t TOPOLOGY | --all [--stopped]]  "
            "Remove lab containers, reclaim images, and report storage saved"
        )
