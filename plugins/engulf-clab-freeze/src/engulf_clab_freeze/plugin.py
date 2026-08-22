from __future__ import annotations

from engulf_api import (
    BeforeGoalAPI,
    GoalResult,
    Invocation,
    StateScope,
)
from engulf_clab_schema_api import (
    SCHEMA_CONTEXTS,
    SCHEMA_PLUGIN_DEPENDENCY,
    LifecycleStage,
    PathBase,
    PluginSchema,
    ValueType,
    record_plugin_schema,
)
from engulf_executable_wrapper_api import (
    ExecutableWrapperPlugin,
    HelpAPI,
)

from .command import main as run_freeze_command

PLUGIN_SCHEMA = (
    PluginSchema("engulf_clab.freeze", package="engulf_clab_freeze")
    .add_command("freeze", "Create a sanitized, portable archive from a lab topology.")
    .add_cli_flag(
        ("-t", "--topology"),
        "Select the source topology file.",
        command="freeze",
        values=ValueType.FILE_PATH,
    )
    .add_cli_flag(
        "--output",
        "Write the archive to this path.",
        command="freeze",
        values=ValueType.FILE_PATH,
    )
    .add_cli_flag(
        "--offline",
        "Include cached source material needed for an offline restore.",
        command="freeze",
    )
    .annotate(
        "freeze",
        lifecycle=(LifecycleStage.BEFORE_GOAL,),
        implies=("normal Containerlab execution is preempted",),
        examples=("eclab freeze -t lab.clab.yml --output share.tar.gz",),
    )
    .annotate(
        "-t",
        commands=("freeze",),
        path_base=PathBase.INVOCATION_DIRECTORY,
        conflicts_with=("implicit single-topology discovery",),
    )
    .annotate(
        "--output",
        commands=("freeze",),
        path_base=PathBase.INVOCATION_DIRECTORY,
    )
    .annotate(
        "--offline",
        commands=("freeze",),
        implies=("include exact cached Containerlab and vrnetlab source material",),
    )
    .use_case(
        "Create a sanitized portable archive without deploying or destroying the lab."
    )
    .reject(
        "Do not assume external files or secrets are dereferenced into the archive."
    )
    .route(
        "freeze-lab",
        "README.md",
        "Read sanitization, archive selection, and offline guarantees.",
    )
    .refer("README.md")
    .refer("AGENTS.md")
)


class FreezePlugin(ExecutableWrapperPlugin):
    """Own the freeze control command before the Containerlab goal runs."""

    plugin_id = "engulf_clab.freeze"
    priority = 200
    plugin_dependencies = (SCHEMA_PLUGIN_DEPENDENCY,)
    context_reads = SCHEMA_CONTEXTS
    context_writes = SCHEMA_CONTEXTS

    def before_goal(
        self, invocation: Invocation, api: BeforeGoalAPI
    ) -> GoalResult[object] | None:
        record_plugin_schema(api, PLUGIN_SCHEMA)
        if not invocation.arguments or invocation.arguments[0] != "freeze":
            return None
        workspace = api.state(StateScope.WORKSPACE)
        offline = "--offline" in invocation.arguments[1:]
        application_name = api.application.short_product_name or api.application.product
        user_state = api.state(StateScope.USER) if offline else None
        # Fixed regardless of edition, so two differently-branded editions
        # freezing the same workspace concurrently actually block each other.
        leases = [f"eclab-freeze:{workspace.root}"]
        if offline:
            leases.extend(
                ("repository-cache:containerlab", "repository-cache:vrnetlab")
            )
        with api.leases(tuple(leases)):
            exit_code = run_freeze_command(
                list(invocation.arguments[1:]),
                workspace,
                user_state=user_state,
                program=f"{application_name} freeze",
                application_name=application_name,
                logger=api.logger,
            )
        return GoalResult.completed(exit_code=exit_code)

    def help(self, api: HelpAPI) -> str:
        del api
        return (
            "  freeze [-t TOPOLOGY] [--output ARCHIVE] [--offline]  "
            "Create a sanitized portable lab archive"
        )
