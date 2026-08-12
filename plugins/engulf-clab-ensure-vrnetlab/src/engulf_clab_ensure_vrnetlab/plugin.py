from __future__ import annotations

import os

from engulf_api import DependencyPosition, InvocationAPI, PluginDependency, StateScope
from engulf_clab_lab_parser import TOPOLOGY_CONTEXT, TopologySession
from engulf_executable_wrapper_api import (
    BeforeCallEvent,
    CallContribution,
    CallMode,
    ExecutableWrapperPlugin,
    HelpAPI,
    PreparedCallEvent,
)

from .checkout import ensure_checkout, require_vrnetlab_dependencies, update_vrnetlab
from .contract import (
    ENSURE_VRNETLAB_PLUGIN_ID,
    VRNETLAB_PATH_CONTEXT,
    VRNETLAB_REPOSITORY_LEASE,
    application_prefix_name,
    vrnetlab_type_env,
)
from .errors import EnsureVrnetlabError
from .logging import use_logger
from .topology import load_topology, topology_needs_vrnetlab, topology_path_from_args


class EnsureVrnetlabPlugin(ExecutableWrapperPlugin):
    plugin_id = ENSURE_VRNETLAB_PLUGIN_ID
    priority = 80
    plugin_dependencies = (
        PluginDependency(
            "engulf_clab.lab_parser",
            preprocess=DependencyPosition.BEFORE,
            postprocess=None,
        ),
    )
    context_writes = frozenset({VRNETLAB_PATH_CONTEXT})
    context_reads = frozenset({TOPOLOGY_CONTEXT})

    def help(self, api: HelpAPI) -> str:
        api.logger.debug("rendering vrnetlab checkout help")
        return (
            "  VRNETLAB_DIR   Use an existing vrnetlab checkout\n"
            "  VRNETLAB_REPO  Override the managed checkout clone source\n"
            "  VRNETLAB_UPDATE=1  Check a Git checkout for updates (daily)\n"
            "  VRNETLAB_VERSION   Clamp to a Git tag, commit, or revision"
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
                application_name=application_prefix_name(api.application),
            ):
                api.logger.debug(
                    "no nodes declare %s; vrnetlab checkout is not needed",
                    vrnetlab_type_env(application_prefix_name(api.application)),
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
            if not isinstance(session, TopologySession): raise EnsureVrnetlabError("invalid shared topology session")
            topology_data = session.original_document()
            if not topology_needs_vrnetlab(
                topology_data,
                application_name=application_prefix_name(api.application),
            ):
                api.logger.debug("no vrnetlab-configured nodes in original topology")
                return

            require_vrnetlab_dependencies()
            with use_logger(api.logger), api.lease(VRNETLAB_REPOSITORY_LEASE):
                state = api.state(StateScope.USER)
                checkout = ensure_checkout(state, os.environ)
                update_vrnetlab(state, checkout, os.environ)
            api.set_context(VRNETLAB_PATH_CONTEXT, str(checkout))
            api.logger.info("published checkout %s", checkout)
        except (EnsureVrnetlabError, OSError) as error:
            api.logger.error("%s", error)
            raise


plugin = EnsureVrnetlabPlugin()
