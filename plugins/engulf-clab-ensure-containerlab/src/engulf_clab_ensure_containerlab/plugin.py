from __future__ import annotations

import os

from engulf_api import BeforeGoalAPI, GoalResult, Invocation, InvocationAPI, StateScope
from engulf_clab_schema_api import (
    SCHEMA_CONTEXTS,
    SCHEMA_PLUGIN_DEPENDENCY,
    SCHEMA_SOURCE_CONTEXT,
    ContainerlabSourceHint,
    ContainerlabSourceKind,
    LifecycleStage,
    PathBase,
    PluginSchema,
    Privilege,
    ValueType,
    publish_containerlab_source,
    record_plugin_schema,
)
from engulf_executable_wrapper_api import (
    AfterCallEvent,
    BeforeCallEvent,
    CallContribution,
    ExecutableWrapperPlugin,
    HelpAPI,
    PreparedCallEvent,
)

from .containerlab import ensure_binary, require_containerlab_dependencies
from .contract import CONTAINERLAB_REPOSITORY_LEASE, ENSURE_CONTAINERLAB_PLUGIN_ID
from .errors import EnsureContainerlabError
from .logging import use_logger

PLUGIN_SCHEMA = (
    PluginSchema("engulf_clab.ensure_containerlab", package="engulf_clab_ensure_containerlab")
    .add_runtime_var(
        "CONTAINERLAB_BIN", "Use this executable Containerlab binary.", values=ValueType.FILE_PATH
    )
    .add_runtime_var(
        "CONTAINERLAB_DIR",
        "Use or build this Containerlab source checkout.",
        values=ValueType.DIRECTORY_PATH,
    )
    .add_runtime_var(
        "CONTAINERLAB_REPO",
        "Override the managed Containerlab Git repository.",
        values=ValueType.URI,
    )
    .add_runtime_var(
        "CONTAINERLAB_UPDATE",
        "Enable the daily managed-checkout update check.",
        values=ValueType.BOOLEAN,
        default=False,
    )
    .add_runtime_var(
        "CONTAINERLAB_VERSION",
        "Clamp Containerlab to a Git tag, commit, or revision.",
        values=ValueType.STRING,
    )
    .use_case("Resolve Containerlab from BIN, DIR, PATH, or a managed checkout in that order.")
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
    .require_host_tool("docker", "Containerlab execution requires an available container runtime.")
    .require_host_tool("git", "Managed source checkout resolution uses Git.")
    .require_host_tool("go", "Building a missing Containerlab binary from source requires Go.")
    .require_privilege(
        Privilege.CONTAINER_RUNTIME,
        "The caller must be authorized to use the configured container runtime.",
    )
    .order(
        LifecycleStage.PREPARE_CALL,
        "Containerlab must be resolved before plugins prepare resources for the wrapped call.",
        before=("engulf_clab.lab_parser",),
    )
    .route(
        "select-containerlab-runtime",
        "README.md",
        "Read exact resolution precedence, checkout, and update rules.",
    )
    .refer("README.md")
    .refer("AGENTS.md")
)


class EnsureContainerlabPlugin(ExecutableWrapperPlugin):
    """Provision a binary only when the standard wrapper executable needs it."""

    plugin_id = ENSURE_CONTAINERLAB_PLUGIN_ID
    # Resolve the executable before every other plugin prepares host resources.
    priority = 110
    plugin_dependencies = (SCHEMA_PLUGIN_DEPENDENCY,)
    context_reads = SCHEMA_CONTEXTS
    context_writes = SCHEMA_CONTEXTS | frozenset({SCHEMA_SOURCE_CONTEXT})

    def __init__(self) -> None:
        self._original_path: str | None = None

    def before_goal(self, invocation: Invocation, api: BeforeGoalAPI) -> GoalResult[object] | None:
        del invocation
        record_plugin_schema(api, PLUGIN_SCHEMA)
        return None

    def help(self, api: HelpAPI) -> str:
        api.logger.debug("rendering Containerlab provisioning help")
        return (
            "  CONTAINERLAB_BIN   Use an executable Containerlab binary\n"
            "  CONTAINERLAB_DIR   Use or build a Containerlab source checkout\n"
            "  CONTAINERLAB_REPO  Override clone source (default: "
            "KarelChanivecky/containerlab ft_fgt_license_support)\n"
            "  CONTAINERLAB_UPDATE=1  Check a Git checkout for updates (daily)\n"
            "  CONTAINERLAB_VERSION   Clamp to a Git tag, commit, or revision\n"
            "  Resolution: BIN, DIR, PATH, then managed checkout; Docker is required, "
            "and source builds require Go."
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
                binary = ensure_binary(api.state(StateScope.USER), os.environ)
            checkout = binary.parent
            if (checkout / "schemas" / "clab.schema.json").is_file():
                source = ContainerlabSourceHint(ContainerlabSourceKind.CHECKOUT, checkout=checkout)
            else:
                source = ContainerlabSourceHint(ContainerlabSourceKind.BINARY, binary=binary)
            publish_containerlab_source(api, source)
            self._original_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{binary.parent}{os.pathsep}{self._original_path}"
        except (EnsureContainerlabError, OSError) as error:
            api.logger.error("%s", error)
            raise

    def after_call(self, event: AfterCallEvent, api: InvocationAPI) -> None:
        if self._original_path is not None:
            os.environ["PATH"] = self._original_path
            self._original_path = None
