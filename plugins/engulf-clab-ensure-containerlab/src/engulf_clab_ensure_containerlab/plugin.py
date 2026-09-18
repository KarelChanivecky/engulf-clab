from __future__ import annotations

import os

from engulf_api import (
    AfterGoalAPI,
    BeforeGoalAPI,
    GoalResult,
    Invocation,
    InvocationAPI,
    StateScope,
)
from engulf_clab_schema_api import (
    SCHEMA_CONTEXTS,
    SCHEMA_SOURCE_CONTEXT,
    LifecycleStage,
    PathBase,
    PluginSchema,
    Privilege,
    SchemaBackedPlugin,
    ValueType,
    publish_containerlab_source,
    record_plugin_schema,
)
from engulf_executable_wrapper_api import (
    AfterCallEvent,
    BeforeCallEvent,
    CallContribution,
    HelpAPI,
    PreparationFailedEvent,
    PreparedCallEvent,
)

from .containerlab import (
    containerlab_source_hint,
    enable_sudoless,
    ensure_binary,
    require_containerlab_dependencies,
    resolved_containerlab_source,
    sudoless_user,
)
from .contract import (
    CONTAINERLAB_REPOSITORY_LEASE,
    ENSURE_CONTAINERLAB_PLUGIN_ID,
    SUDOLESS_COMMAND,
)
from .errors import EnsureContainerlabError
from .logging import use_logger

PLUGIN_SCHEMA = (
    PluginSchema("engulf_clab.ensure_containerlab", package="engulf_clab_ensure_containerlab")
    .add_command(
        SUDOLESS_COMMAND,
        "Enable Containerlab SUID plus clab_admins and Docker group access.",
    )
    .add_runtime_var(
        "CONTAINERLAB_BIN",
        "Select a Containerlab executable; the matching CLI flag takes precedence.",
        values=ValueType.FILE_PATH,
    )
    .add_cli_flag(
        "--eclab-containerlab-bin",
        "Use this executable Containerlab binary.",
        values=ValueType.FILE_PATH,
        environment="CONTAINERLAB_BIN",
    )
    .add_runtime_var(
        "CONTAINERLAB_DIR",
        "Select a Containerlab source checkout; the matching CLI flag takes precedence.",
        values=ValueType.DIRECTORY_PATH,
    )
    .add_cli_flag(
        "--eclab-containerlab-dir",
        "Use or build this Containerlab source checkout.",
        values=ValueType.DIRECTORY_PATH,
        environment="CONTAINERLAB_DIR",
    )
    .add_runtime_var(
        "CONTAINERLAB_REPO",
        "Override the managed Containerlab Git repository; the matching CLI flag wins.",
        values=ValueType.URI,
    )
    .add_cli_flag(
        "--eclab-containerlab-repo",
        "Override the managed Containerlab Git repository.",
        values=ValueType.URI,
        environment="CONTAINERLAB_REPO",
    )
    .add_runtime_var(
        "CONTAINERLAB_UPDATE",
        "Enable the daily managed-checkout update check; the matching CLI flag wins.",
        values=ValueType.BOOLEAN,
        default=False,
    )
    .add_cli_flag(
        "--eclab-containerlab-update",
        "Enable the daily managed-checkout update check.",
        environment="CONTAINERLAB_UPDATE",
    )
    .add_runtime_var(
        "CONTAINERLAB_VERSION",
        "Clamp Containerlab to a Git revision; the matching CLI flag takes precedence.",
        values=ValueType.STRING,
    )
    .add_cli_flag(
        "--eclab-containerlab-version",
        "Clamp Containerlab to a Git tag, commit, or revision.",
        values=ValueType.STRING,
        environment="CONTAINERLAB_VERSION",
    )
    .use_case("Resolve Containerlab from BIN, DIR, PATH, or a managed checkout in that order.")
    .use_case("Enable sudo-less Containerlab and Docker operation for the current user.")
    .annotate(
        SUDOLESS_COMMAND,
        lifecycle=(LifecycleStage.BEFORE_GOAL,),
        requires=("Run as the unprivileged user who needs Containerlab access.",),
        implies=(
            "Preempt normal Containerlab execution and invoke sudo for host account changes.",
            "Grant effective root-level access through clab_admins and docker membership.",
        ),
        examples=("eclab sudoless",),
    )
    .annotate(
        "CONTAINERLAB_BIN",
        lifecycle=(LifecycleStage.PREPARE_CALL,),
        path_base=PathBase.INVOCATION_DIRECTORY,
        implies=("Takes precedence over CONTAINERLAB_DIR, PATH, and the managed checkout.",),
    )
    .annotate(
        "CONTAINERLAB_DIR",
        lifecycle=(LifecycleStage.PREPARE_CALL,),
        path_base=PathBase.INVOCATION_DIRECTORY,
        requires=("a valid Containerlab checkout containing go.mod",),
    )
    .annotate("CONTAINERLAB_REPO", lifecycle=(LifecycleStage.PREPARE_CALL,))
    .annotate(
        "CONTAINERLAB_UPDATE",
        lifecycle=(LifecycleStage.PREPARE_CALL,),
        implies=("perform at most one update check per day",),
    )
    .annotate(
        "CONTAINERLAB_VERSION",
        lifecycle=(LifecycleStage.PREPARE_CALL,),
        implies=("enable revision checking and clamp the checkout",),
    )
    .annotate(
        "--eclab-containerlab-bin",
        lifecycle=(LifecycleStage.BEFORE_GOAL, LifecycleStage.PREPARE_CALL),
        path_base=PathBase.INVOCATION_DIRECTORY,
        implies=("takes precedence over every Containerlab environment default",),
    )
    .annotate(
        "--eclab-containerlab-dir",
        lifecycle=(LifecycleStage.BEFORE_GOAL, LifecycleStage.PREPARE_CALL),
        path_base=PathBase.INVOCATION_DIRECTORY,
        requires=("a valid Containerlab checkout containing go.mod",),
    )
    .annotate(
        "--eclab-containerlab-repo",
        lifecycle=(LifecycleStage.BEFORE_GOAL, LifecycleStage.PREPARE_CALL),
    )
    .annotate(
        "--eclab-containerlab-update",
        lifecycle=(LifecycleStage.BEFORE_GOAL, LifecycleStage.PREPARE_CALL),
        implies=("perform at most one update check per day",),
    )
    .annotate(
        "--eclab-containerlab-version",
        lifecycle=(LifecycleStage.BEFORE_GOAL, LifecycleStage.PREPARE_CALL),
        implies=("enable revision checking and clamp the checkout",),
    )
    .require_host_tool("docker", "Containerlab execution requires an available container runtime.")
    .require_host_tool("git", "Managed source checkout resolution uses Git.")
    .require_host_tool("go", "Building a missing Containerlab binary from source requires Go.")
    .require_host_tool(
        "sudo",
        "Host setup and privileged Containerlab children use sudo when sudo-less access is absent.",
    )
    .require_privilege(
        Privilege.CONTAINER_RUNTIME,
        "The caller must be authorized to use the configured container runtime.",
    )
    .require_privilege(
        Privilege.ROOT,
        "The sudoless command obtains root privileges through sudo for host setup.",
        commands=(SUDOLESS_COMMAND,),
    )
    .order(
        LifecycleStage.PREPARE_CALL,
        "Containerlab must be resolved before plugins prepare resources for the wrapped call.",
        before=("engulf_clab.lab_parser",),
    )
    .route(
        "select-containerlab-runtime",
        "USAGE.md",
        "Read exact resolution precedence, checkout, and update rules.",
    )
    .refer("USAGE.md")
)


class EnsureContainerlabPlugin(SchemaBackedPlugin):
    """Provision a binary only when the standard wrapper executable needs it."""

    plugin_id = ENSURE_CONTAINERLAB_PLUGIN_ID
    schema = PLUGIN_SCHEMA
    # Resolve the executable before every other plugin prepares host resources.
    priority = 110
    context_reads = SCHEMA_CONTEXTS | frozenset({SCHEMA_SOURCE_CONTEXT})
    context_writes = SCHEMA_CONTEXTS | frozenset({SCHEMA_SOURCE_CONTEXT})

    def __init__(self) -> None:
        self._original_path: str | None = None
        self._path_prepared = False

    def before_goal(self, invocation: Invocation, api: BeforeGoalAPI) -> GoalResult[object] | None:
        record_plugin_schema(api, PLUGIN_SCHEMA)
        if invocation.arguments and invocation.arguments[0] == SUDOLESS_COMMAND:
            try:
                username = sudoless_user()
                with use_logger(api.logger), api.lease(CONTAINERLAB_REPOSITORY_LEASE):
                    binary = ensure_binary(api.state(StateScope.USER), invocation.environment)
                    enable_sudoless(binary, username)
                api.logger.warning(
                    "user %s now has root-equivalent Containerlab and Docker access; "
                    "log out and back in before using the new group memberships",
                    username,
                )
                return GoalResult.completed()
            except (EnsureContainerlabError, OSError) as error:
                api.logger.error("%s", error)
                return GoalResult.failed(1, error=str(error))
        source = containerlab_source_hint(
            api.state(StateScope.USER),
            invocation.environment,
        )
        publish_containerlab_source(api, source)
        return None

    def after_goal(
        self,
        invocation: Invocation,
        result: GoalResult[object],
        api: AfterGoalAPI,
    ) -> GoalResult[object]:
        del invocation
        if result.exit_code != 0:
            # A plugin between this source producer and the terminal schema
            # consumer may have stopped preprocessing. Acknowledge the hint so
            # its useful primary error is not followed by a secondary warning.
            api.get_context(SCHEMA_SOURCE_CONTEXT)
        return result

    def help(self, api: HelpAPI) -> str:
        api.logger.debug("rendering Containerlab provisioning help")
        return (
            "  sudoless                          Enable SUID, clab_admins, and Docker access\n"
            "  --eclab-containerlab-bin PATH     Use an executable binary\n"
            "  --eclab-containerlab-dir DIR      Use or build a source checkout\n"
            "  --eclab-containerlab-repo URL     Override clone source (default: "
            "KarelChanivecky/containerlab ft_fgt_license_support)\n"
            "  --eclab-containerlab-update       Check a Git checkout for updates (daily)\n"
            "  --eclab-containerlab-version REV  Clamp to a Git tag, commit, or revision\n"
            "  CONTAINERLAB_{BIN,DIR,REPO,UPDATE,VERSION} are persistent environment defaults; "
            "matching CLI options override them.\n"
            "  Resolution: BIN, DIR, PATH, then managed checkout; Docker is required, "
            "and source builds require Go.\n"
            "  Privileged Containerlab operations use sudo unless sudo-less access is available."
        )

    def analyze_call(
        self,
        event: BeforeCallEvent,
        api: InvocationAPI,
    ) -> CallContribution | None:
        return None

    def prepare_call(self, event: PreparedCallEvent, api: InvocationAPI) -> None:
        if event.binary != "containerlab":
            return
        try:
            require_containerlab_dependencies()
            with use_logger(api.logger), api.lease(CONTAINERLAB_REPOSITORY_LEASE):
                binary = ensure_binary(api.state(StateScope.USER), event.environment)
            publish_containerlab_source(api, resolved_containerlab_source(binary))
            self._original_path = os.environ.get("PATH")
            current_path = self._original_path or ""
            os.environ["PATH"] = f"{binary.parent}{os.pathsep}{current_path}"
            self._path_prepared = True
        except (EnsureContainerlabError, OSError) as error:
            api.logger.error("%s", error)
            raise

    def prepare_failed(self, event: PreparationFailedEvent, api: InvocationAPI) -> None:
        del event, api
        self._restore_path()

    def after_call(self, event: AfterCallEvent, api: InvocationAPI) -> None:
        del event, api
        self._restore_path()

    def _restore_path(self) -> None:
        if self._path_prepared:
            if self._original_path is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = self._original_path
            self._path_prepared = False
            self._original_path = None
