from __future__ import annotations

import os

from engulf_api import (
    BeforeGoalAPI,
    DependencyPosition,
    GoalResult,
    Invocation,
    InvocationAPI,
    PluginDependency,
    StateScope,
)
from engulf_clab_lab_parser import TOPOLOGY_CONTEXT, TopologySession
from engulf_clab_schema_api import (
    SCHEMA_CONTEXTS,
    SCHEMA_PLUGIN_DEPENDENCY,
    SCHEMA_VRNETLAB_SOURCE_CONTEXT,
    LifecycleStage,
    PathBase,
    PluginSchema,
    Privilege,
    ValueType,
    publish_vrnetlab_source,
    record_plugin_schema,
)
from engulf_executable_wrapper_api import (
    BeforeCallEvent,
    CallContribution,
    CallMode,
    ExecutableWrapperPlugin,
    HelpAPI,
    PreparedCallEvent,
)

from .checkout import (
    ensure_checkout,
    require_vrnetlab_dependencies,
    resolved_vrnetlab_source,
    update_vrnetlab,
    vrnetlab_source_hint,
)
from .contract import (
    ENSURE_VRNETLAB_PLUGIN_ID,
    VRNETLAB_PATH_CONTEXT,
    VRNETLAB_REPOSITORY_LEASE,
    vrnetlab_type_env,
)
from .errors import EnsureVrnetlabError
from .logging import use_logger
from .topology import load_topology, topology_needs_vrnetlab, topology_path_from_args

PLUGIN_SCHEMA = (
    PluginSchema("engulf_clab.ensure_vrnetlab", package="engulf_clab_ensure_vrnetlab")
    .add_node_var(
        "ECLAB_VRNETLAB_TYPE",
        "Opt a node into vrnetlab and select its builder directory.",
        values=ValueType.STRING,
    )
    .add_runtime_var(
        "VRNETLAB_DIR", "Use an existing vrnetlab checkout.", values=ValueType.DIRECTORY_PATH
    )
    .add_runtime_var("VRNETLAB_REPO", "Override the vrnetlab Git repository.", values=ValueType.URI)
    .add_runtime_var(
        "VRNETLAB_UPDATE",
        "Enable the daily checkout update check.",
        values=ValueType.BOOLEAN,
        default=False,
    )
    .add_runtime_var(
        "VRNETLAB_VERSION",
        "Clamp the checkout to a Git tag, commit, or revision.",
        values=ValueType.STRING,
    )
    .annotate(
        "ECLAB_VRNETLAB_TYPE",
        commands=("deploy",),
        lifecycle=(LifecycleStage.ANALYZE_CALL, LifecycleStage.PREPARE_CALL),
        shared_with=("engulf_clab.vrnetlab_build",),
        implies=("a vrnetlab checkout is required before image construction",),
        examples=("vendor/router",),
    )
    .annotate("VRNETLAB_DIR", commands=("deploy",), path_base=PathBase.INVOCATION_DIRECTORY)
    .annotate("VRNETLAB_REPO", commands=("deploy",))
    .annotate(
        "VRNETLAB_UPDATE",
        commands=("deploy",),
        implies=("perform at most one update check per day",),
    )
    .annotate(
        "VRNETLAB_VERSION",
        commands=("deploy",),
        implies=("enable revision checking and clamp the checkout",),
    )
    .require_host_tool(
        "git", "Managed vrnetlab checkout resolution uses Git.", commands=("deploy",)
    )
    .require_host_tool(
        "docker", "vrnetlab builders construct container images.", commands=("deploy",)
    )
    .require_host_tool(
        "qemu-img", "Image preparation validates and converts virtual disks.", commands=("deploy",)
    )
    .require_host_tool(
        "qemu-system-x86_64",
        "vrnetlab image construction boots the virtual appliance.",
        commands=("deploy",),
    )
    .require_privilege(
        Privilege.CONTAINER_RUNTIME,
        "The caller must be authorized to use Docker.",
        commands=("deploy",),
    )
    .use_case("Provision vrnetlab only when a deploy contains an opted-in node.")
    .reject("Do not provision vrnetlab for a topology without ECLAB_VRNETLAB_TYPE.")
    .order(
        LifecycleStage.PREPARE_CALL,
        "The checkout must be available before the vrnetlab image builder consumes it.",
        after=("engulf_clab.lab_parser",),
        before=("engulf_clab.vrnetlab_build", "engulf_clab.lab_writer"),
    )
    .route(
        "prepare-vrnetlab",
        "README.md",
        "Read checkout selection, prerequisites, and conditional lifecycle.",
    )
    .refer("README.md")
    .refer("AGENTS.md")
)


class EnsureVrnetlabPlugin(ExecutableWrapperPlugin):
    plugin_id = ENSURE_VRNETLAB_PLUGIN_ID
    priority = 80
    plugin_dependencies = (
        PluginDependency(
            "engulf_clab.lab_parser",
            preprocess=DependencyPosition.BEFORE,
            postprocess=None,
        ),
        SCHEMA_PLUGIN_DEPENDENCY,
    )
    context_writes = (
        frozenset({VRNETLAB_PATH_CONTEXT, SCHEMA_VRNETLAB_SOURCE_CONTEXT})
        | SCHEMA_CONTEXTS
    )
    context_reads = frozenset({TOPOLOGY_CONTEXT}) | SCHEMA_CONTEXTS

    def before_goal(self, invocation: Invocation, api: BeforeGoalAPI) -> GoalResult[object] | None:
        record_plugin_schema(api, PLUGIN_SCHEMA)
        source = vrnetlab_source_hint(
            api.state(StateScope.USER),
            invocation.environment,
        )
        publish_vrnetlab_source(api, source)
        return None

    def help(self, api: HelpAPI) -> str:
        api.logger.debug("rendering vrnetlab checkout help")
        return (
            "  VRNETLAB_DIR   Use an existing vrnetlab checkout\n"
            "  VRNETLAB_REPO  Override clone source (default: "
            "KarelChanivecky/vrnetlab ft_faster_reads)\n"
            "  VRNETLAB_UPDATE=1  Check a Git checkout for updates (daily)\n"
            "  VRNETLAB_VERSION   Clamp to a Git tag, commit, or revision\n"
            "  Provisioning runs only for opted-in deploys and requires Docker, qemu-img, "
            "and qemu-system-x86_64."
        )

    def analyze_call(
        self,
        event: BeforeCallEvent,
        api: InvocationAPI,
    ) -> CallContribution | None:
        if event.mode is CallMode.HELP or not event.wrapper_args:
            return None

        command, *rest = event.wrapper_args
        if command != "deploy":
            return None

        try:
            topology_path = topology_path_from_args(tuple(rest))
            topology_data = load_topology(topology_path)
            if not topology_needs_vrnetlab(topology_data):
                api.logger.debug(
                    "no nodes declare %s; vrnetlab checkout is not needed",
                    vrnetlab_type_env(),
                )
                return None
        except (EnsureVrnetlabError, OSError) as error:
            api.logger.error("%s", error)
            return CallContribution(preempt_exit_code=1)

        return None

    def prepare_call(self, event: PreparedCallEvent, api: InvocationAPI) -> None:
        command, *_ = event.wrapper_args
        if command != "deploy":
            return

        try:
            session = api.require_context(TOPOLOGY_CONTEXT)
            if not isinstance(session, TopologySession):
                raise EnsureVrnetlabError("invalid shared topology session")
            topology_data = session.original_document()
            if not topology_needs_vrnetlab(topology_data):
                api.logger.debug("no vrnetlab-configured nodes in original topology")
                return

            require_vrnetlab_dependencies()
            with use_logger(api.logger), api.lease(VRNETLAB_REPOSITORY_LEASE):
                state = api.state(StateScope.USER)
                checkout = ensure_checkout(state, os.environ)
                update_vrnetlab(state, checkout, os.environ)
            api.set_context(VRNETLAB_PATH_CONTEXT, str(checkout))
            publish_vrnetlab_source(api, resolved_vrnetlab_source(checkout))
            api.logger.info("published checkout %s", checkout)
        except (EnsureVrnetlabError, OSError) as error:
            api.logger.error("%s", error)
            raise


plugin = EnsureVrnetlabPlugin()
