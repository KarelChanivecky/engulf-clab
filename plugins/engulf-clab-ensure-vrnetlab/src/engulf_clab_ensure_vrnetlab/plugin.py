from __future__ import annotations

import os

from engulf_api import InvocationAPI, StateScope
from engulf_executable_wrapper_api import (
    BeforeCallEvent,
    CallContribution,
    CallMode,
    ExecutableWrapperPlugin,
    HelpAPI,
    PreparedCallEvent,
)

from .checkout import ensure_checkout
from .contract import (
    ENSURE_VRNETLAB_PLUGIN_ID,
    VRNETLAB_PATH_CONTEXT,
    VRNETLAB_REPOSITORY_LEASE,
)
from .errors import EnsureVrnetlabError
from .logging import use_logger
from .topology import load_topology, topology_needs_vrnetlab, topology_path_from_args


class EnsureVrnetlabPlugin(ExecutableWrapperPlugin):
    plugin_id = ENSURE_VRNETLAB_PLUGIN_ID
    priority = 80
    context_writes = frozenset({VRNETLAB_PATH_CONTEXT})

    def help(self, api: HelpAPI) -> str:
        api.logger.debug("rendering vrnetlab checkout help")
        return (
            "  VRNETLAB_DIR   Use an existing vrnetlab checkout\n"
            "  VRNETLAB_REPO  Override the managed checkout clone source"
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
            if not topology_needs_vrnetlab(
                topology_data,
                application_name=api.application.display_name,
            ):
                return None
        except (EnsureVrnetlabError, OSError) as error:
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
            if not topology_needs_vrnetlab(
                topology_data,
                application_name=api.application.display_name,
            ):
                return

            with use_logger(api.logger), api.lease(VRNETLAB_REPOSITORY_LEASE):
                checkout = ensure_checkout(api.state(StateScope.USER), os.environ)
            api.set_context(VRNETLAB_PATH_CONTEXT, str(checkout))
            api.logger.info("published checkout %s", checkout)
        except (EnsureVrnetlabError, OSError) as error:
            api.logger.error("%s", error)
            raise


plugin = EnsureVrnetlabPlugin()
