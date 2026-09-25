from __future__ import annotations

from engulf_api import (
    BeforeGoalAPI,
    GoalResult,
    Invocation,
    StateScope,
)
from engulf_clab_schema_api import (
    SCHEMA_CONTEXTS,
    SCHEMA_SOURCE_CONTEXT,
    SCHEMA_VRNETLAB_SOURCE_CONTEXT,
    LifecycleStage,
    PathBase,
    PluginSchema,
    Privilege,
    SchemaBackedPlugin,
    ValueType,
    record_plugin_schema,
)
from engulf_executable_wrapper_api import HelpAPI

from .command import main as run_freeze_command
from .defrost import lease as defrost_lease
from .defrost import main as run_defrost_command

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
    .add_cli_flag(
        "--eclab-with-runtime",
        "Bundle a wheelhouse and enforce recorded Containerlab and vrnetlab identities.",
        command="freeze",
    )
    .add_cli_flag(
        "--external-image",
        "Declare an image that the recipient supplies; repeat for additional dependencies.",
        command="freeze",
        values=ValueType.IMAGE_REFERENCE,
        repeatable=True,
    )
    .add_cli_flag(
        "--bundle-image",
        "Export an image into an offline archive.",
        command="freeze",
        values=ValueType.IMAGE_REFERENCE,
        repeatable=True,
    )
    .add_cli_flag(
        "--include-pki-secrets",
        "Include exportable PKI identities when the PKI contributor is installed.",
        command="freeze",
    )
    .add_cli_flag(
        "--pki-passphrase-file",
        "Read the PKI export passphrase from an owner-private file.",
        command="freeze",
        values=ValueType.FILE_PATH,
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
        conflicts_with=("--external-image",),
        implies=(
            "bundle runtime/tools and images whose rebuild may require network access",
        ),
    )
    .annotate("--eclab-with-runtime", commands=("freeze",))
    .annotate("--external-image", commands=("freeze",), conflicts_with=("--offline",))
    .annotate(
        "--bundle-image",
        commands=("freeze",),
        requires=("--offline",),
        host_tools=("docker",),
        privilege=Privilege.CONTAINER_RUNTIME,
    )
    .add_command(
        "defrost",
        "Expand a frozen archive into a runnable lab directory and restore its env initializer.",
    )
    .add_cli_argument(
        "defrost",
        "ARCHIVE",
        "Select the frozen archive to expand.",
        values=ValueType.FILE_PATH,
    )
    .add_cli_flag(
        "--into",
        "Write the lab into this directory.",
        command="defrost",
        values=ValueType.DIRECTORY_PATH,
    )
    .add_cli_flag(
        "--force",
        "Replace a directory an earlier defrost created at the destination.",
        command="defrost",
    )
    .add_cli_flag(
        "--license",
        "Answer one frozen license prompt as NODE=VALUE, or every prompt as VALUE.",
        command="defrost",
        values=ValueType.STRING,
        repeatable=True,
    )
    .add_cli_flag(
        "--env",
        "Provide a topology environment value to the recipient initializer as NAME=VALUE.",
        command="defrost",
        values=ValueType.STRING,
        repeatable=True,
    )
    .add_cli_flag(
        "--no-license-prompt",
        "Keep frozen license markers instead of asking for paths.",
        command="defrost",
    )
    .add_cli_flag(
        "--no-runtime",
        "Skip runtime preparation; a runtime archive launcher prepares it on first use.",
        command="defrost",
    )
    .add_cli_flag(
        "--no-images",
        "Skip selection of bundled Docker image archives.",
        command="defrost",
    )
    .add_cli_flag(
        "--load-images",
        "Load selected bundled image archives into Docker now.",
        command="defrost",
    )
    .add_cli_flag(
        "--skip-env-init",
        "Do not run the archive's recipient environment initializer.",
        command="defrost",
    )
    .add_cli_flag(
        "--pki-authority",
        "Resolve one frozen PKI binding as BINDING=REF.",
        command="defrost",
        values=ValueType.STRING,
        repeatable=True,
    )
    .add_cli_flag(
        "--no-pki-prompt",
        "Keep unresolved PKI bindings as actionable manifest markers.",
        command="defrost",
    )
    .add_cli_flag(
        "--pki-passphrase-file",
        "Read the PKI import passphrase from an owner-private file.",
        command="defrost",
        values=ValueType.FILE_PATH,
    )
    .annotate(
        "defrost",
        lifecycle=(LifecycleStage.BEFORE_GOAL,),
        implies=("normal Containerlab execution is preempted",),
        examples=("eclab defrost share.tar.gz --into labs/demo",),
    )
    .annotate(
        "ARCHIVE",
        commands=("defrost",),
        path_base=PathBase.INVOCATION_DIRECTORY,
    )
    .annotate(
        "--into",
        commands=("defrost",),
        path_base=PathBase.INVOCATION_DIRECTORY,
        conflicts_with=("the default directory named after the archive",),
    )
    .annotate(
        "--force",
        commands=("defrost",),
        requires=("the destination holds an earlier defrost record",),
    )
    .annotate(
        "--license",
        commands=("defrost",),
        path_base=PathBase.LICENSE_POOL,
        conflicts_with=("--no-license-prompt",),
    )
    .annotate(
        "--env",
        commands=("defrost",),
        conflicts_with=("--skip-env-init",),
    )
    .annotate(
        "--no-license-prompt",
        commands=("defrost",),
        implies=("deploy resolves every frozen license instead",),
    )
    .annotate(
        "--no-runtime",
        commands=("defrost",),
        implies=("run-eclab.sh prepares the runtime at first use",),
    )
    .annotate(
        "--load-images",
        commands=("defrost",),
        conflicts_with=("--no-images",),
        host_tools=("docker",),
        privilege=Privilege.CONTAINER_RUNTIME,
    )
    .use_case(
        "Create a sanitized portable archive without deploying or destroying the lab."
    )
    .use_case(
        "Use the lean default for recipient image inputs, or --offline to bundle images."
    )
    .use_case(
        "Expand a received archive into a lab with local licenses, images, and runtime."
    )
    .reject(
        "Do not assume external files or secrets are dereferenced into the archive."
    )
    .route(
        "freeze-lab",
        "USAGE.md",
        "Read sanitization, archive selection, and offline guarantees.",
    )
    .route(
        "defrost-lab",
        "USAGE.md",
        "Read expansion, license answers, image selection, and runtime preparation.",
    )
    .refer("USAGE.md")
)


class FreezePlugin(SchemaBackedPlugin):
    """Own the freeze and defrost control commands before the Containerlab goal runs."""

    plugin_id = "engulf_clab.freeze"
    schema = PLUGIN_SCHEMA
    priority = 200
    context_reads = SCHEMA_CONTEXTS | frozenset(
        {SCHEMA_SOURCE_CONTEXT, SCHEMA_VRNETLAB_SOURCE_CONTEXT}
    )
    context_writes = SCHEMA_CONTEXTS

    def before_goal(
        self, invocation: Invocation, api: BeforeGoalAPI
    ) -> GoalResult[object] | None:
        record_plugin_schema(api, PLUGIN_SCHEMA)
        if not invocation.arguments:
            return None
        if invocation.arguments[0] == "defrost":
            self._acknowledge_schema_sources(api)
            return self._defrost(invocation, api)
        if invocation.arguments[0] != "freeze":
            return None
        self._acknowledge_schema_sources(api)
        workspace = api.state(StateScope.WORKSPACE)
        offline = "--offline" in invocation.arguments[1:]
        application_name = api.application.short_product_name or api.application.product
        user_state = api.state(StateScope.USER)
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
                environment=invocation.environment,
            )
        return GoalResult.completed(exit_code=exit_code)

    @staticmethod
    def _acknowledge_schema_sources(api: BeforeGoalAPI) -> None:
        """Consume terminal schema inputs when a control command preempts it."""
        api.get_context(SCHEMA_SOURCE_CONTEXT)
        api.get_context(SCHEMA_VRNETLAB_SOURCE_CONTEXT)

    def _defrost(
        self, invocation: Invocation, api: BeforeGoalAPI
    ) -> GoalResult[object]:
        """Expand one archive under a lease covering only its destination."""
        arguments = list(invocation.arguments[1:])
        application_name = api.application.short_product_name or api.application.product
        # Fixed regardless of edition, for the same reason the freeze lease is:
        # two differently-branded editions writing one destination must block.
        with api.leases((defrost_lease(arguments, invocation.cwd),)):
            exit_code = run_defrost_command(
                arguments,
                program=f"{application_name} defrost",
                application_name=application_name,
                logger=api.logger,
                environment=invocation.environment,
                cwd=invocation.cwd,
                user_state=api.state(StateScope.USER).directory,
            )
        return GoalResult.completed(exit_code=exit_code)

    def help(self, api: HelpAPI) -> str:
        del api
        return (
            "  freeze [-t TOPOLOGY] [--output ARCHIVE] [--eclab-with-runtime | --offline]  "
            "Create a sanitized portable lab archive\n"
            "    Default: record compatibility; leave runtime and images to the recipient.\n"
            "    --eclab-with-runtime: wheelhouse and pinned tools; --offline: bundle runtime, tools, images.\n"
            "    --external-image IMAGE (non-offline) / --bundle-image IMAGE (offline).\n"
            "  defrost ARCHIVE [--into DIRECTORY] [--pki-authority BINDING=REF]  "
            "Expand a frozen archive into a runnable lab"
        )
