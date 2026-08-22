from __future__ import annotations

import os
import subprocess

from engulf_api import (
    BeforeGoalAPI,
    DependencyPosition,
    GoalResult,
    Invocation,
    InvocationAPI,
    PluginDependency,
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
    ValueType,
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

from .config import (
    DEFAULT_VRNETLAB_BUILD_JOBS,
    build_requests_from_topology,
    vrnetlab_build_jobs,
)
from .errors import VrnetlabError
from .images import ensure_images
from .logging import use_logger
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
        "Select a qcow2 file or supported image archive.",
        values=ValueType.FILE_PATH,
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
        "Limit concurrent vrnetlab image builds.",
        values=ValueType.POSITIVE_INTEGER,
        default=2,
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
        "Image construction consumes the parsed topology and resolved checkout before serialization.",
        after=("engulf_clab.ensure_vrnetlab", "engulf_clab.lab_parser"),
        before=("engulf_clab.lab_writer",),
    )
    .route(
        "build-vrnetlab-image",
        "README.md",
        "Read image-source precedence, builder layout, and fingerprint behavior.",
    )
    .refer("README.md")
    .refer("AGENTS.md")
)


class VrnetlabPlugin(ExecutableWrapperPlugin):
    plugin_id = "engulf_clab.vrnetlab_build"
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
        SCHEMA_PLUGIN_DEPENDENCY,
    )
    context_reads = frozenset({VRNETLAB_PATH_CONTEXT, TOPOLOGY_CONTEXT}) | SCHEMA_CONTEXTS
    context_writes = SCHEMA_CONTEXTS

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
            "  Runtime environment:\n"
            f"    {prefix}_VRNETLAB_IMG_PATH  Select a qcow2 or supported archive source\n"
            f"    {prefix}_VM_IMG              Compatibility image-source alias\n"
            f"    {prefix}_VM_SRC              Older image-source alias\n"
            f"    {prefix}_VRNETLAB_BUILD_JOBS Concurrent image builds "
            f"(default: {DEFAULT_VRNETLAB_BUILD_JOBS})"
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
            requests = build_requests_from_topology(topology_path, topology_data, os.environ)
            vrnetlab_build_jobs()
            if not requests:
                api.logger.debug(
                    "no nodes declare %s; no vrnetlab images to build",
                    vrnetlab_type_env(),
                )
                return None
        except (VrnetlabError, OSError, subprocess.CalledProcessError) as error:
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
                raise VrnetlabError("invalid shared topology session")
            topology_path = session.path
            topology_data = session.original_document()
            requests = build_requests_from_topology(topology_path, topology_data, os.environ)
            if not requests:
                api.logger.debug("no vrnetlab image-build requests in original topology")
                return

            checkout_context = api.get_context(VRNETLAB_PATH_CONTEXT)
            state_store = api.state(StateScope.USER)
            with use_logger(api.logger):
                api.logger.info("using topology %s", topology_path)
                ensure_images(
                    requests,
                    api=api,
                    checkout_context=checkout_context,
                    state_store=state_store,
                    source_environment=vrnetlab_image_path_env(),
                    max_workers=vrnetlab_build_jobs(),
                )
        except (VrnetlabError, OSError, subprocess.CalledProcessError) as error:
            api.logger.error("%s", error)
            raise


plugin = VrnetlabPlugin()
