from __future__ import annotations

from engulf_api import (
    AfterGoalAPI,
    BeforeGoalAPI,
    GoalResult,
    Invocation,
    InvocationAPI,
    StateScope,
)
from engulf_clab_lab_parser import (
    TOPOLOGY_CONTEXT,
    TopologySession,
    is_topology_mutation_command,
)
from engulf_clab_schema_api import (
    SCHEMA_CONTEXTS,
    SCHEMA_VRNETLAB_SOURCE_CONTEXT,
    LifecycleStage,
    PathBase,
    PluginSchema,
    Privilege,
    SchemaBackedPlugin,
    ValueType,
    publish_vrnetlab_source,
    record_plugin_schema,
)
from engulf_executable_wrapper_api import (
    BeforeCallEvent,
    CallContribution,
    CallMode,
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
        "VRNETLAB_DIR",
        "Select an existing vrnetlab checkout; the matching CLI flag takes precedence.",
        values=ValueType.DIRECTORY_PATH,
    )
    .add_cli_flag(
        "--eclab-vrnetlab-dir",
        "Use an existing vrnetlab checkout.",
        values=ValueType.DIRECTORY_PATH,
        environment="VRNETLAB_DIR",
    )
    .add_runtime_var(
        "VRNETLAB_REPO",
        "Override the vrnetlab Git repository; the matching CLI flag takes precedence.",
        values=ValueType.URI,
    )
    .add_cli_flag(
        "--eclab-vrnetlab-repo",
        "Override the vrnetlab Git repository.",
        values=ValueType.URI,
        environment="VRNETLAB_REPO",
    )
    .add_runtime_var(
        "VRNETLAB_UPDATE",
        "Enable the daily checkout update check; the matching CLI flag takes precedence.",
        values=ValueType.BOOLEAN,
        default=False,
    )
    .add_cli_flag(
        "--eclab-vrnetlab-update",
        "Enable the daily checkout update check.",
        environment="VRNETLAB_UPDATE",
    )
    .add_runtime_var(
        "VRNETLAB_VERSION",
        "Clamp vrnetlab to a Git revision; the matching CLI flag takes precedence.",
        values=ValueType.STRING,
    )
    .add_cli_flag(
        "--eclab-vrnetlab-version",
        "Clamp the checkout to a Git tag, commit, or revision.",
        values=ValueType.STRING,
        environment="VRNETLAB_VERSION",
    )
    .annotate(
        "ECLAB_VRNETLAB_TYPE",
        commands=("deploy", "redeploy"),
        lifecycle=(LifecycleStage.ANALYZE_CALL, LifecycleStage.PREPARE_CALL),
        shared_with=("engulf_clab.vrnetlab_build",),
        implies=("a vrnetlab checkout is required before image construction",),
        examples=("vendor/router",),
    )
    .annotate("VRNETLAB_DIR", commands=("deploy", "redeploy"), path_base=PathBase.INVOCATION_DIRECTORY)
    .annotate("VRNETLAB_REPO", commands=("deploy", "redeploy"))
    .annotate(
        "VRNETLAB_UPDATE",
        commands=("deploy", "redeploy"),
        implies=("perform at most one update check per day",),
    )
    .annotate(
        "VRNETLAB_VERSION",
        commands=("deploy", "redeploy"),
        implies=("enable revision checking and clamp the checkout",),
    )
    .annotate(
        "--eclab-vrnetlab-dir",
        commands=("deploy", "redeploy"),
        path_base=PathBase.INVOCATION_DIRECTORY,
    )
    .annotate("--eclab-vrnetlab-repo", commands=("deploy", "redeploy"))
    .annotate(
        "--eclab-vrnetlab-update",
        commands=("deploy", "redeploy"),
        implies=("perform at most one update check per day",),
    )
    .annotate(
        "--eclab-vrnetlab-version",
        commands=("deploy", "redeploy"),
        implies=("enable revision checking and clamp the checkout",),
    )
    .require_host_tool(
        "git", "Managed vrnetlab checkout resolution uses Git.", commands=("deploy", "redeploy")
    )
    .require_host_tool(
        "docker", "vrnetlab builders construct container images.", commands=("deploy", "redeploy")
    )
    .require_host_tool(
        "qemu-img", "Image preparation validates and converts virtual disks.", commands=("deploy", "redeploy")
    )
    .require_host_tool(
        "qemu-system-x86_64",
        "vrnetlab image construction boots the virtual appliance.",
        commands=("deploy", "redeploy"),
    )
    .require_privilege(
        Privilege.CONTAINER_RUNTIME,
        "The caller must be authorized to use Docker.",
        commands=("deploy", "redeploy"),
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
        "USAGE.md",
        "Read checkout selection, prerequisites, and conditional lifecycle.",
    )
    .refer("USAGE.md")
)


class EnsureVrnetlabPlugin(SchemaBackedPlugin):
    plugin_id = ENSURE_VRNETLAB_PLUGIN_ID
    schema = PLUGIN_SCHEMA
    priority = 80
    context_writes = (
        frozenset({VRNETLAB_PATH_CONTEXT, SCHEMA_VRNETLAB_SOURCE_CONTEXT}) | SCHEMA_CONTEXTS
    )
    context_reads = (
        frozenset({TOPOLOGY_CONTEXT, SCHEMA_VRNETLAB_SOURCE_CONTEXT}) | SCHEMA_CONTEXTS
    )

    def before_goal(self, invocation: Invocation, api: BeforeGoalAPI) -> GoalResult[object] | None:
        record_plugin_schema(api, PLUGIN_SCHEMA)
        source = vrnetlab_source_hint(
            api.state(StateScope.USER),
            invocation.environment,
        )
        publish_vrnetlab_source(api, source)
        return None

    def after_goal(
        self,
        invocation: Invocation,
        result: GoalResult[object],
        api: AfterGoalAPI,
    ) -> GoalResult[object]:
        del invocation
        if result.exit_code != 0:
            # If preprocessing stopped before the terminal schema plugin, keep
            # the primary error from gaining a secondary unused-context warning.
            api.get_context(SCHEMA_VRNETLAB_SOURCE_CONTEXT)
        return result

    def help(self, api: HelpAPI) -> str:
        api.logger.debug("rendering vrnetlab checkout help")
        return (
            "  --eclab-vrnetlab-dir DIR      Use an existing vrnetlab checkout\n"
            "  --eclab-vrnetlab-repo URL     Override clone source (default: "
            "KarelChanivecky/vrnetlab ft_faster_reads)\n"
            "  --eclab-vrnetlab-update       Check a Git checkout for updates (daily)\n"
            "  --eclab-vrnetlab-version REV  Clamp to a Git tag, commit, or revision\n"
            "  VRNETLAB_{DIR,REPO,UPDATE,VERSION} are persistent environment defaults; "
            "matching CLI options override them.\n"
            "  Provisioning runs only for opted-in deploys or redeploys and requires Docker, qemu-img, "
            "and qemu-system-x86_64."
        )

    def analyze_call(
        self,
        event: BeforeCallEvent,
        api: InvocationAPI,
    ) -> CallContribution | None:
        if event.mode is CallMode.HELP or not event.wrapper_args:
            return None

        _command, *rest = event.wrapper_args
        if not is_topology_mutation_command(event.wrapper_args):
            return None

        try:
            topology_path = topology_path_from_args(tuple(rest))
            topology_data = load_topology(topology_path, event.environment)
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
        if not is_topology_mutation_command(event.wrapper_args):
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
                checkout = ensure_checkout(state, event.environment)
                update_vrnetlab(state, checkout, event.environment)
            api.set_context(VRNETLAB_PATH_CONTEXT, str(checkout))
            publish_vrnetlab_source(api, resolved_vrnetlab_source(checkout))
            api.logger.info("published checkout %s", checkout)
        except (EnsureVrnetlabError, OSError) as error:
            api.logger.error("%s", error)
            raise


plugin = EnsureVrnetlabPlugin()
