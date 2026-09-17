from __future__ import annotations

from engulf_api import (
    AfterGoalAPI,
    BeforeGoalAPI,
    GoalResult,
    GoalResultStatus,
    Invocation,
)
from engulf_clab_lab_registry_api import (
    LAB_REGISTRY_COMMIT_CONTEXT,
    LAB_REGISTRY_CONTEXT,
    LabRegistryError,
    RegistryCommit,
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

from .command import ReclaimError, execute, parse_options, plan
from .docker import DockerClient, DockerError
from .model import ReclaimPlan

# The plan this invocation staged in before_goal for its own after_goal to
# execute. Module-local: it is the plugin's private handoff between callbacks.
RECLAIM_PLAN_CONTEXT = "engulf_clab.reclaim.plan"

PLUGIN_SCHEMA = (
    PluginSchema("engulf_clab.reclaim", package="engulf_clab_reclaim")
    .add_command(
        "reclaim",
        "Remove lab containers and reclaim lab-owned Docker image storage.",
    )
    .add_cli_flag(
        ("-t", "--topology"),
        "Select one lab topology instead of discovering it in the current directory.",
        command="reclaim",
        values=ValueType.FILE_PATH,
    )
    .add_cli_flag(
        "--all",
        "Reclaim storage for every known lab only when all are already destroyed.",
        command="reclaim",
    )
    .add_cli_flag(
        "--stopped",
        "With --all, reclaim only labs whose containers exist but are stopped.",
        command="reclaim",
    )
    .annotate(
        "reclaim",
        lifecycle=(LifecycleStage.BEFORE_GOAL, LifecycleStage.AFTER_GOAL),
        implies=(
            "normal Containerlab execution is preempted",
            "planned observations are committed to the lab registry before any deletion",
            "deletion aborts without deleting anything when that commit does not happen",
            "a registry that changed past the plan is re-validated before deletion",
            "lab containers, writable layers, anonymous volumes, and selected images are deleted",
            "lab directories and registry records are preserved",
            "Docker-reported storage saved is measured and logged",
        ),
        host_tools=("docker",),
        privilege=Privilege.CONTAINER_RUNTIME,
        examples=(
            "eclab reclaim -t lab.clab.yml",
            "eclab reclaim --all",
            "eclab reclaim --all --stopped",
        ),
    )
    .annotate(
        "-t",
        commands=("reclaim",),
        path_base=PathBase.INVOCATION_DIRECTORY,
        conflicts_with=("--all",),
    )
    .annotate(
        "--all",
        commands=("reclaim",),
        conflicts_with=("-t or --topology",),
        implies=("the command fails if any known lab still has containers",),
    )
    .annotate(
        "--stopped",
        commands=("reclaim",),
        requires=("--all",),
        implies=("running and destroyed labs are not selected",),
    )
    .require_host_tool(
        "docker",
        "Docker supplies lab discovery and removes containers, volumes, and images.",
        commands=("reclaim",),
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


class ReclaimPlugin(SchemaBackedPlugin):
    """Own the destructive Docker-only storage-reclamation command."""

    plugin_id = "engulf_clab.reclaim"
    schema = PLUGIN_SCHEMA
    priority = 195
    context_reads = SCHEMA_CONTEXTS | frozenset(
        {LAB_REGISTRY_CONTEXT, LAB_REGISTRY_COMMIT_CONTEXT, RECLAIM_PLAN_CONTEXT}
    )
    context_writes = SCHEMA_CONTEXTS | frozenset({RECLAIM_PLAN_CONTEXT})

    def before_goal(
        self, invocation: Invocation, api: BeforeGoalAPI
    ) -> GoalResult[object] | None:
        record_plugin_schema(api, PLUGIN_SCHEMA)
        if not invocation.arguments or invocation.arguments[0] != "reclaim":
            return None
        application_name = api.application.short_product_name or api.application.product
        arguments = invocation.arguments[1:]
        options = parse_options(arguments, f"{application_name} reclaim")
        registry = lab_registry(api)
        # A registry that could not be read cannot confirm what this run should
        # preserve, so reclamation stops before planning or deleting anything.
        if not registry.persistent:
            api.logger.error(
                "%s reclaim: the lab registry is unreadable; refusing to reclaim "
                "storage before lab ownership can be preserved",
                application_name,
            )
            return GoalResult.completed(exit_code=1)
        docker = DockerClient()
        with api.leases(("eclab-reclaim:docker",)):
            try:
                reclaim_plan = plan(
                    arguments,
                    cwd=invocation.cwd,
                    environment=invocation.environment,
                    registry=registry,
                    docker=docker,
                    program=f"{application_name} reclaim",
                    options=options,
                )
            except (DockerError, ReclaimError, LabRegistryError) as error:
                api.logger.error("%s reclaim: %s", application_name, error)
                return GoalResult.completed(exit_code=1)
            # Record the intent the registry owner commits in its own after_goal,
            # which runs before this plugin's deletion step. Deleting here would
            # race that durable write; the plan is staged instead.
            registry.upsert(reclaim_plan.observations)
        api.set_context(RECLAIM_PLAN_CONTEXT, reclaim_plan)
        return GoalResult.completed()

    def after_goal(
        self,
        invocation: Invocation,
        result: GoalResult[object],
        api: AfterGoalAPI,
    ) -> GoalResult[object]:
        if (
            not invocation.arguments
            or invocation.arguments[0] != "reclaim"
            or result.status is not GoalResultStatus.COMPLETED
            or result.exit_code != 0
        ):
            return result
        reclaim_plan = api.get_context(RECLAIM_PLAN_CONTEXT)
        if not isinstance(reclaim_plan, ReclaimPlan):
            return result
        # The registry owner ordered itself before this plugin in postprocess, so
        # its commit already ran; execute against that durable outcome.
        outcome = api.get_context(LAB_REGISTRY_COMMIT_CONTEXT)
        commit = outcome if isinstance(outcome, RegistryCommit) else RegistryCommit(
            committed=False, revision=reclaim_plan.base_revision
        )
        application_name = api.application.short_product_name or api.application.product
        with api.leases(("eclab-reclaim:docker",)):
            exit_code = execute(
                reclaim_plan,
                commit=commit,
                docker=DockerClient(),
                logger=api.logger,
            )
        if exit_code:
            api.logger.error(
                "%s reclaim: reclamation did not complete", application_name
            )
        return GoalResult.completed(exit_code=exit_code)

    def help(self, api: HelpAPI) -> str:
        del api
        return (
            "  reclaim [-t TOPOLOGY | --all [--stopped]]  "
            "Remove lab containers, reclaim images, and report storage saved"
        )
