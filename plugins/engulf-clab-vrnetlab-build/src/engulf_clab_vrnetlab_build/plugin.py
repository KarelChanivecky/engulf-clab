from __future__ import annotations

import os
import subprocess

from engulf_api import DependencyPosition, InvocationAPI, PluginDependency, StateScope
from engulf_clab_ensure_vrnetlab import (
    ENSURE_VRNETLAB_PLUGIN_ID,
    LABEL_PREFIX,
    VRNETLAB_PATH_CONTEXT,
    vrnetlab_image_path_env,
    vrnetlab_type_env,
)
from engulf_clab_lab_parser import TOPOLOGY_CONTEXT, TopologySession
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
    )
    context_reads = frozenset({VRNETLAB_PATH_CONTEXT, TOPOLOGY_CONTEXT})

    def help(self, api: HelpAPI) -> str:
        del api
        prefix = LABEL_PREFIX
        return (
            "  Node YAML env fields:\n"
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
        command, *rest = event.wrapper_args
        if command != "deploy":
            return

        try:
            topology_path = topology_path_from_args(tuple(rest))
            session = api.require_context(TOPOLOGY_CONTEXT)
            if not isinstance(session, TopologySession): raise VrnetlabError("invalid shared topology session")
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
