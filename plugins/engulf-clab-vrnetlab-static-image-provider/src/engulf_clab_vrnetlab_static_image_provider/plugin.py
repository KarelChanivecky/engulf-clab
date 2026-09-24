from __future__ import annotations

import subprocess

from engulf_api import (
    BeforeGoalAPI,
    GoalResult,
    Invocation,
    InvocationAPI,
    RegistrationAPI,
)
from engulf_clab_lab_parser import (
    TOPOLOGY_CONTEXT,
    TopologySession,
    is_topology_mutation_command,
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
from engulf_clab_vrnetlab_build_api import (
    VRNETLAB_BUILD_CONTEXT,
    VrnetlabBuildAPI,
    get_build_context,
)
from engulf_executable_wrapper_api import (
    ArgumentRegistry,
    BeforeCallEvent,
    CallContribution,
    CallMode,
    CompletionCandidate,
    CompletionContext,
    CompletionRegistry,
    HelpAPI,
    Match,
    PreparedCallEvent,
    Runtime,
)

from .contract import LABEL_PREFIX, vrnetlab_type_env
from .config import (
    DEFAULT_VRNETLAB_BUILD_JOBS,
    build_requests_from_topology,
    vrnetlab_build_jobs,
)
from .errors import VrnetlabError
from .options import (
    IMAGE_OPTION,
    complete_image_option,
    complete_image_option_argument,
    parse_image_options,
)
from .topology import load_topology, topology_path_from_args

PLUGIN_ID = "engulf_clab.vrnetlab_static_image_provider"


def _image_option_visible(context: CompletionContext) -> bool:
    """Hide the flag itself when its selector argument is being completed."""
    return context.current != IMAGE_OPTION and Match.any_prior_word(("deploy", "redeploy")).matches(
        context
    )


PLUGIN_SCHEMA = (
    PluginSchema(PLUGIN_ID, package="engulf_clab_vrnetlab_static_image_provider")
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
        "Override a node with NODE=PATH; default=PATH supplies one builder-type fallback.",
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
        commands=("deploy", "redeploy"),
        lifecycle=(LifecycleStage.ANALYZE_CALL, LifecycleStage.PREPARE_CALL),
        examples=("vrnetlab/my-lab-router:1.0.0",),
    )
    .annotate(
        "ECLAB_VRNETLAB_TYPE",
        commands=("deploy", "redeploy"),
        lifecycle=(LifecycleStage.ANALYZE_CALL, LifecycleStage.PREPARE_CALL),
        requires=("the selected builder exists below the resolved vrnetlab checkout",),
        shared_with=("engulf_clab.ensure_vrnetlab",),
        examples=("vendor/router",),
    )
    .annotate(
        "ECLAB_VRNETLAB_IMG_PATH",
        commands=("deploy", "redeploy"),
        requires=("ECLAB_VRNETLAB_TYPE",),
        path_base=PathBase.TOPOLOGY_DIRECTORY,
    )
    .annotate(
        "ECLAB_VM_IMG",
        commands=("deploy", "redeploy"),
        implies=("compatibility fallback for ECLAB_VRNETLAB_IMG_PATH",),
    )
    .annotate(
        "ECLAB_VM_SRC",
        commands=("deploy", "redeploy"),
        implies=("legacy fallback after ECLAB_VM_IMG",),
    )
    .annotate(
        "ECLAB_VRNETLAB_BUILD_JOBS",
        commands=("deploy", "redeploy"),
        lifecycle=(LifecycleStage.PREPARE_CALL,),
    )
    .annotate(
        "--eclab-vrnetlab-image",
        commands=("deploy", "redeploy"),
        lifecycle=(LifecycleStage.ANALYZE_CALL, LifecycleStage.PREPARE_CALL),
        path_base=PathBase.TOPOLOGY_DIRECTORY,
        implies=(
            "node selector, then one-type default source, then node YAML and environment",
        ),
        examples=("default=/images/router.qcow2", "router=/images/router.zip"),
    )
    .annotate(
        "--eclab-vrnetlab-build-jobs",
        commands=("deploy", "redeploy"),
        lifecycle=(LifecycleStage.ANALYZE_CALL, LifecycleStage.PREPARE_CALL),
    )
    .require_host_tool(
        "docker", "Build the final vrnetlab container image.", commands=("deploy", "redeploy")
    )
    .require_host_tool(
        "qemu-img",
        "Inspect and convert the selected image source.",
        commands=("deploy", "redeploy"),
    )
    .require_privilege(
        Privilege.CONTAINER_RUNTIME,
        "The caller must be authorized to use Docker.",
        commands=("deploy", "redeploy"),
    )
    .use_case("Build a missing vrnetlab image for an explicitly opted-in node before deploy.")
    .reject("Do not infer a builder type from the image tag; declare ECLAB_VRNETLAB_TYPE.")
    .order(
        LifecycleStage.PREPARE_CALL,
        "This source provider publishes resolved paths before the shared vrnetlab builder runs.",
        after=("engulf_clab.lab_parser",),
        before=("engulf_clab.vrnetlab_build",),
    )
    .route(
        "build-vrnetlab-image",
        "USAGE.md",
        "Read image-source precedence, builder layout, and fingerprint behavior.",
    )
    .refer("USAGE.md")
)


class VrnetlabPlugin(SchemaBackedPlugin):
    plugin_id = PLUGIN_ID
    schema = PLUGIN_SCHEMA
    priority = 75
    context_reads = frozenset({TOPOLOGY_CONTEXT, VRNETLAB_BUILD_CONTEXT}) | SCHEMA_CONTEXTS
    context_writes = frozenset({VRNETLAB_BUILD_CONTEXT}) | SCHEMA_CONTEXTS

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
            description="Override a node's configured vrnetlab image source",
            value_completer=Runtime(
                "image-selector",
                complete_image_option,
            ),
            suggest_assignment=False,
            repeatable=True,
            when=_image_option_visible,
        )
        registry.option(
            "--eclab-vrnetlab-build-jobs",
            takes_value=True,
            metavar="POSITIVE_INTEGER",
            description="Limit concurrent vrnetlab image builds",
            value_completer=Runtime(
                "vrnetlab-build-jobs",
                _complete_build_jobs,
            ),
            when=Match.cursor_at(0) | Match.any_prior_word(("deploy", "redeploy")),
            environment=f"{LABEL_PREFIX}_VRNETLAB_BUILD_JOBS",
        )

    def register_completions(
        self,
        registry: CompletionRegistry,
        api: RegistrationAPI,
    ) -> None:
        super().register_completions(registry, api)
        registry.provider(
            Runtime(
                "image-selector-option",
                complete_image_option_argument,
                Match.current_prefix(IMAGE_OPTION),
            )
        )

    def before_goal(self, invocation: Invocation, api: BeforeGoalAPI) -> GoalResult[object] | None:
        del invocation
        record_plugin_schema(api, PLUGIN_SCHEMA)
        return None

    def help(self, api: HelpAPI) -> str:
        del api
        prefix = LABEL_PREFIX
        return (
            "  Node YAML fields:\n"
            "    image                      Use a lab-unique requested Docker tag\n"
            f"    {prefix}_VRNETLAB_TYPE      Opt in and select the vrnetlab builder\n"
            "  Wrapper options:\n"
            "    --eclab-vrnetlab-image NODE=FILE  Override one node's configured source\n"
            "      default=FILE                    Supply a fallback for one builder type\n"
            "    --eclab-vrnetlab-build-jobs COUNT Concurrent image builds "
            f"(default: {DEFAULT_VRNETLAB_BUILD_JOBS})\n"
            "  Resolved sources are published to the shared vrnetlab builder, which "
            "constructs opted-in node images before image resolution.\n"
            f"  {prefix}_VRNETLAB_IMG_PATH remains the persistent image fallback; "
            "CLI selectors win over node YAML.\n"
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
            if parsed.selectors and not is_topology_mutation_command(parsed.arguments):
                raise VrnetlabError(
                    f"{IMAGE_OPTION} must follow a single-topology deploy or redeploy command"
                )
            if not parsed.arguments:
                return CallContribution(removals=parsed.removals) if parsed.removals else None
            _command, *rest = parsed.arguments
            if not is_topology_mutation_command(parsed.arguments):
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
        try:
            parsed = parse_image_options(event.wrapper_args)
            if not parsed.arguments:
                return
            if not is_topology_mutation_command(parsed.arguments):
                return

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
            if not requests:
                api.logger.debug(
                    "no nodes declare %s; no vrnetlab sources to publish",
                    vrnetlab_type_env(),
                )
                return

            context = get_build_context(api, create=True)
            if context is None:
                raise RuntimeError("vrnetlab build context was not initialized")
            build_api = VrnetlabBuildAPI(context)
            build_api.set_build_jobs(vrnetlab_build_jobs(event.environment))

            sources = tuple(request.source for request in requests)
            if (
                sources
                and all(source is not None for source in sources)
                and len(set(sources)) == 1
                and len({request.builder_type for request in requests}) == 1
            ):
                source = sources[0]
                assert source is not None
                build_api.set_image_source(source)
            else:
                for request in requests:
                    if request.source is not None:
                        build_api.set_image_source(request.source, request.node_name)
            api.logger.debug("published vrnetlab sources from topology %s", topology_path)
        except (
            VrnetlabError,
            OSError,
            ValueError,
            TypeError,
            RuntimeError,
            subprocess.SubprocessError,
        ) as error:
            api.logger.error("%s", error)
            raise


def _deploy_completion(context: CompletionContext) -> bool:
    if context.cursor_index == 0:
        return True
    return bool({"deploy", "redeploy"}.intersection(context.words[: context.cursor_index]))


def _after_deploy_completion(context: CompletionContext) -> bool:
    return bool({"deploy", "redeploy"}.intersection(context.words[: context.cursor_index]))


def _complete_build_jobs(context: CompletionContext) -> tuple[CompletionCandidate, ...]:
    default = str(DEFAULT_VRNETLAB_BUILD_JOBS)
    if default.startswith(context.current):
        return (CompletionCandidate(default, "Default value"),)
    return ()


plugin = VrnetlabPlugin()
