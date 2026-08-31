from __future__ import annotations

import subprocess

from engulf_api import (
    BeforeGoalAPI,
    DependencyPosition,
    GoalResult,
    Invocation,
    InvocationAPI,
    PluginDependency,
    RegistrationAPI,
    StateScope,
)
from engulf_clab_ensure_vrnetlab import (
    ENSURE_VRNETLAB_PLUGIN_ID,
    LABEL_PREFIX,
    VRNETLAB_PATH_CONTEXT,
    vrnetlab_image_path_env,
    vrnetlab_type_env,
)
from engulf_clab_lab_parser import TOPOLOGY_CONTEXT, TopologySession
from engulf_clab_schema_api import (
    SCHEMA_CONTEXTS,
    SCHEMA_PLUGIN_DEPENDENCY,
    LifecycleStage,
    PathBase,
    PluginSchema,
    Privilege,
    SchemaBackedPlugin,
    ValueType,
    record_plugin_schema,
)
from engulf_docker_image_api import (
    IMAGE_PROVIDER_CONTEXT,
    ImageProviderPlugin,
    RegisteredImageProvider,
    register_image_provider,
)
from engulf_executable_wrapper_api import (
    ArgumentRegistry,
    BeforeCallEvent,
    CallContribution,
    CallMode,
    CompletionCandidate,
    CompletionContext,
    HelpAPI,
    PreparedCallEvent,
)

from .config import (
    DEFAULT_VRNETLAB_BUILD_JOBS,
    build_requests_from_topology,
    vrnetlab_build_jobs,
)
from .errors import VrnetlabError
from .images import ensure_images
from .logging import use_logger
from .options import IMAGE_OPTION, complete_image_option, parse_image_options
from .provider import VRNETLAB_PROVIDER_ID, VrnetlabBuildProvider
from .topology import load_topology, topology_path_from_args

PLUGIN_SCHEMA = (
    PluginSchema("engulf_clab.vrnetlab_build", package="engulf_clab_vrnetlab_build")
    .add_node_prop(
        "image",
        "Use a lab-unique requested image tag so independently launched labs do not share it.",
        values=ValueType.IMAGE_REFERENCE,
    )
    .add_node_var(
        "ECLAB_VRNETLAB_TYPE",
        "Opt a node into image construction and select its vrnetlab builder.",
        values=ValueType.STRING,
    )
    .add_runtime_var(
        "ECLAB_VRNETLAB_IMG_PATH",
        "Select the persistent fallback vrnetlab image source.",
        values=ValueType.FILE_PATH,
    )
    .add_cli_flag(
        "--eclab-vrnetlab-image",
        "Select a repeatable NODE=PATH source; default=PATH supplies the fallback.",
        values=ValueType.STRING,
        repeatable=True,
    )
    .add_runtime_var(
        "ECLAB_VM_IMG",
        "Compatibility alias for the vrnetlab image source.",
        values=ValueType.FILE_PATH,
        deprecated=True,
        replacement="ECLAB_VRNETLAB_IMG_PATH",
    )
    .add_runtime_var(
        "ECLAB_VM_SRC",
        "Legacy alias for the vrnetlab image source.",
        values=ValueType.FILE_PATH,
        deprecated=True,
        replacement="ECLAB_VRNETLAB_IMG_PATH",
    )
    .add_runtime_var(
        "ECLAB_VRNETLAB_BUILD_JOBS",
        "Limit concurrent vrnetlab image builds; the matching CLI flag takes precedence.",
        values=ValueType.POSITIVE_INTEGER,
        default=2,
    )
    .add_cli_flag(
        "--eclab-vrnetlab-build-jobs",
        "Limit concurrent vrnetlab image builds.",
        values=ValueType.POSITIVE_INTEGER,
        environment="ECLAB_VRNETLAB_BUILD_JOBS",
    )
    .annotate(
        "image",
        commands=("deploy",),
        lifecycle=(LifecycleStage.ANALYZE_CALL, LifecycleStage.PREPARE_CALL),
        examples=("vrnetlab/my-lab-router:1.0.0",),
    )
    .annotate(
        "ECLAB_VRNETLAB_TYPE",
        commands=("deploy",),
        lifecycle=(LifecycleStage.ANALYZE_CALL, LifecycleStage.PREPARE_CALL),
        requires=("the selected builder exists below the resolved vrnetlab checkout",),
        shared_with=("engulf_clab.ensure_vrnetlab",),
        examples=("vendor/router",),
    )
    .annotate(
        "ECLAB_VRNETLAB_IMG_PATH",
        commands=("deploy",),
        requires=("ECLAB_VRNETLAB_TYPE",),
        path_base=PathBase.TOPOLOGY_DIRECTORY,
    )
    .annotate(
        "ECLAB_VM_IMG",
        commands=("deploy",),
        implies=("compatibility fallback for ECLAB_VRNETLAB_IMG_PATH",),
    )
    .annotate("ECLAB_VM_SRC", commands=("deploy",), implies=("legacy fallback after ECLAB_VM_IMG",))
    .annotate(
        "ECLAB_VRNETLAB_BUILD_JOBS", commands=("deploy",), lifecycle=(LifecycleStage.PREPARE_CALL,)
    )
    .annotate(
        "--eclab-vrnetlab-image",
        commands=("deploy",),
        lifecycle=(LifecycleStage.ANALYZE_CALL, LifecycleStage.PREPARE_CALL),
        path_base=PathBase.TOPOLOGY_DIRECTORY,
        implies=("specific node, node YAML, default selector, then environment precedence",),
        examples=("default=/images/router.qcow2", "router=/images/router.zip"),
    )
    .annotate(
        "--eclab-vrnetlab-build-jobs",
        commands=("deploy",),
        lifecycle=(LifecycleStage.ANALYZE_CALL, LifecycleStage.PREPARE_CALL),
    )
    .require_host_tool("docker", "Build the final vrnetlab container image.", commands=("deploy",))
    .require_host_tool(
        "qemu-img", "Inspect and convert the selected image source.", commands=("deploy",)
    )
    .require_privilege(
        Privilege.CONTAINER_RUNTIME,
        "The caller must be authorized to use Docker.",
        commands=("deploy",),
    )
    .use_case("Build a missing vrnetlab image for an explicitly opted-in node before deploy.")
    .reject("Do not infer a builder type from the image tag; declare ECLAB_VRNETLAB_TYPE.")
    .order(
        LifecycleStage.PREPARE_CALL,
        "Image construction consumes the parsed topology and resolved checkout before image resolution and serialization.",
        after=("engulf_clab.ensure_vrnetlab", "engulf_clab.lab_parser"),
        before=("engulf_clab.image_build", "engulf_clab.lab_writer"),
    )
    .route(
        "build-vrnetlab-image",
        "USAGE.md",
        "Read image-source precedence, builder layout, and fingerprint behavior.",
    )
    .refer("USAGE.md")
)


class VrnetlabPlugin(SchemaBackedPlugin):
    plugin_id = "engulf_clab.vrnetlab_build"
    schema = PLUGIN_SCHEMA
    priority = 75
    plugin_dependencies = (
        PluginDependency(
            ENSURE_VRNETLAB_PLUGIN_ID,
            preprocess=DependencyPosition.BEFORE,
            postprocess=None,
        ),
        PluginDependency(
            "engulf_clab.lab_parser",
            preprocess=DependencyPosition.BEFORE,
            postprocess=None,
        ),
        PluginDependency(
            "engulf_clab.image_build",
            preprocess=DependencyPosition.AFTER,
            postprocess=None,
        ),
        SCHEMA_PLUGIN_DEPENDENCY,
    )
    context_reads = (
        frozenset({VRNETLAB_PATH_CONTEXT, TOPOLOGY_CONTEXT, IMAGE_PROVIDER_CONTEXT})
        | SCHEMA_CONTEXTS
    )
    # register_image_provider appends to the provider registry, so registration is a
    # read-modify-write of IMAGE_PROVIDER_CONTEXT — it must appear in both sets.
    context_writes = frozenset({IMAGE_PROVIDER_CONTEXT}) | SCHEMA_CONTEXTS

    def __init__(self) -> None:
        self._provider = VrnetlabBuildProvider()

    def register_arguments(
        self,
        registry: ArgumentRegistry,
        api: RegistrationAPI,
    ) -> None:
        del api
        registry.option(
            IMAGE_OPTION,
            takes_value=True,
            metavar="NODE=FILE",
            description="Select a per-node vrnetlab image source",
            value_completer=complete_image_option,
            suggest_assignment=False,
            repeatable=True,
            when=_after_deploy_completion,
        )
        registry.option(
            "--eclab-vrnetlab-build-jobs",
            takes_value=True,
            metavar="POSITIVE_INTEGER",
            description="Limit concurrent vrnetlab image builds",
            value_completer=_complete_build_jobs,
            when=_deploy_completion,
            environment=f"{LABEL_PREFIX}_VRNETLAB_BUILD_JOBS",
        )

    def before_goal(self, invocation: Invocation, api: BeforeGoalAPI) -> GoalResult[object] | None:
        del invocation
        record_plugin_schema(api, PLUGIN_SCHEMA)
        register_image_provider(
            api,
            RegisteredImageProvider(
                VRNETLAB_PROVIDER_ID,
                self._provider,
                priority=self.priority,
            ),
        )
        return None

    def help(self, api: HelpAPI) -> str:
        del api
        prefix = LABEL_PREFIX
        return (
            "  Node YAML fields:\n"
            "    image                      Use a lab-unique requested Docker tag\n"
            f"    {prefix}_VRNETLAB_TYPE      Opt in and select the vrnetlab builder\n"
            "  Wrapper options:\n"
            "    --eclab-vrnetlab-image NODE=FILE  Select a repeatable node image source\n"
            "      default=FILE                    Fallback when no node source is selected\n"
            "    --eclab-vrnetlab-build-jobs COUNT Concurrent image builds "
            f"(default: {DEFAULT_VRNETLAB_BUILD_JOBS})\n"
            "  Opted-in node images are provisioned through the image-build graph: "
            "this plugin's provider offers a vrnetlab build recipe for each requested "
            "tag ahead of the pull fallback.\n"
            f"  {prefix}_VRNETLAB_IMG_PATH remains the persistent image fallback; "
            "node selectors and node YAML win.\n"
            f"  {prefix}_VRNETLAB_BUILD_JOBS is the persistent job default; its CLI option wins.\n"
            f"  {prefix}_VM_IMG and {prefix}_VM_SRC remain legacy image-source aliases."
        )

    def analyze_call(
        self,
        event: BeforeCallEvent,
        api: InvocationAPI,
    ) -> CallContribution | None:
        if event.mode is CallMode.HELP or not event.wrapper_args:
            return None

        try:
            parsed = parse_image_options(event.wrapper_args)
            if parsed.selectors and event.wrapper_args[0] != "deploy":
                raise VrnetlabError(f"{IMAGE_OPTION} must follow the deploy command")
            if not parsed.arguments:
                return CallContribution(removals=parsed.removals) if parsed.removals else None
            command, *rest = parsed.arguments
            if command != "deploy":
                return CallContribution(removals=parsed.removals) if parsed.removals else None
            topology_path = topology_path_from_args(tuple(rest))
            topology_data = load_topology(topology_path, event.environment)
            requests = build_requests_from_topology(
                topology_path,
                topology_data,
                event.environment,
                image_selectors=parsed.selectors,
            )
            vrnetlab_build_jobs(event.environment)
            if not requests:
                api.logger.debug(
                    "no nodes declare %s; no vrnetlab images to build",
                    vrnetlab_type_env(),
                )
                return CallContribution(removals=parsed.removals) if parsed.removals else None
        except (VrnetlabError, OSError, subprocess.CalledProcessError) as error:
            api.logger.error("%s", error)
            return CallContribution(preempt_exit_code=1)

        return CallContribution(removals=parsed.removals) if parsed.removals else None

    def prepare_call(self, event: PreparedCallEvent, api: InvocationAPI) -> None:
        parsed = parse_image_options(event.wrapper_args)
        if not parsed.arguments:
            return
        command, *_ = parsed.arguments
        if command != "deploy":
            return

        try:
            session = api.require_context(TOPOLOGY_CONTEXT)
            if not isinstance(session, TopologySession):
                raise VrnetlabError("invalid shared topology session")
            topology_path = session.path
            topology_data = session.original_document()
            requests = build_requests_from_topology(
                topology_path,
                topology_data,
                event.environment,
                image_selectors=parsed.selectors,
            )
            checkout_context = api.get_context(VRNETLAB_PATH_CONTEXT)
            # Populate the provider map before the build so engulf_clab.image_build —
            # which runs after this prepare_call — can resolve these image references to
            # the vrnetlab provider instead of the docker-pull fallback, for this deploy.
            self._provider.refresh_requests(requests, checkout_context=checkout_context)

            if not requests:
                api.logger.debug("no vrnetlab image-build requests in original topology")
                return

            state_store = api.state(StateScope.USER)
            with use_logger(api.logger):
                api.logger.info("using topology %s", topology_path)
                ensure_images(
                    requests,
                    api=api,
                    checkout_context=checkout_context,
                    state_store=state_store,
                    source_environment=vrnetlab_image_path_env(),
                    max_workers=vrnetlab_build_jobs(event.environment),
                )
        except (VrnetlabError, OSError, subprocess.CalledProcessError) as error:
            api.logger.error("%s", error)
            raise


def _deploy_completion(context: CompletionContext) -> bool:
    if context.cursor_index == 0:
        return True
    return "deploy" in context.words[: context.cursor_index]


def _after_deploy_completion(context: CompletionContext) -> bool:
    return "deploy" in context.words[: context.cursor_index]


def _complete_build_jobs(context: CompletionContext) -> tuple[CompletionCandidate, ...]:
    default = str(DEFAULT_VRNETLAB_BUILD_JOBS)
    if default.startswith(context.current):
        return (CompletionCandidate(default, "Default value"),)
    return ()


plugin = VrnetlabPlugin()

# Adapter exposed under the org_engulf_docker_image goal entry point. It wraps the SAME
# provider instance as `plugin` so references recorded by plugin.prepare_call are the
# ones provide() answers for, whichever dispatch path drives resolution.
image_plugin = ImageProviderPlugin(
    VRNETLAB_PROVIDER_ID, plugin._provider, priority=VrnetlabPlugin.priority
)
