from __future__ import annotations

import os
import subprocess

from engulf_api import DependencyPosition, InvocationAPI, PluginDependency, StateScope
from engulf_clab_ensure_vrnetlab import (
    ENSURE_VRNETLAB_PLUGIN_ID,
    VRNETLAB_PATH_CONTEXT,
    environment_prefix,
    vrnetlab_image_path_env,
)
from engulf_executable_wrapper_api import (
    BeforeCallEvent,
    CallContribution,
    CallMode,
    ExecutableWrapperPlugin,
    HelpAPI,
    PreparedCallEvent,
)

from .config import build_requests_from_topology
from .errors import VrnetlabError
from .images import ensure_images
from .logging import use_logger
from .topology import load_topology, topology_path_from_args


class VrnetlabPlugin(ExecutableWrapperPlugin):
    plugin_id = "dev.karel.engulf_clab.vrnetlab"
    priority = 75
    plugin_dependencies = (
        PluginDependency(
            ENSURE_VRNETLAB_PLUGIN_ID,
            preprocess=DependencyPosition.BEFORE,
            postprocess=None,
        ),
    )
    context_reads = frozenset({VRNETLAB_PATH_CONTEXT})

    def help(self, api: HelpAPI) -> str:
        api.logger.debug("rendering vrnetlab build help")
        prefix = environment_prefix(api.application.display_name)
        return (
            f"  {prefix}_VRNETLAB_TYPE      Build configured vrnetlab node images\n"
            f"  {prefix}_VRNETLAB_IMG_PATH  Select a qcow2 or supported archive source"
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
            requests = build_requests_from_topology(
                topology_path,
                topology_data,
                os.environ,
                application_name=api.application.display_name,
            )
            if not requests:
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
            topology_data = load_topology(topology_path)
            requests = build_requests_from_topology(
                topology_path,
                topology_data,
                os.environ,
                application_name=api.application.display_name,
            )
            if not requests:
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
                    source_environment=vrnetlab_image_path_env(api.application.display_name),
                )
        except (VrnetlabError, OSError, subprocess.CalledProcessError) as error:
            api.logger.error("%s", error)
            raise


plugin = VrnetlabPlugin()
