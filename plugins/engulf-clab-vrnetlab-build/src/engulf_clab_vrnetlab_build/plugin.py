from __future__ import annotations

import subprocess

from engulf_api import (
    BeforeGoalAPI,
    GoalResult,
    Invocation,
    InvocationAPI,
    StateScope,
)
from engulf_clab_ensure_vrnetlab import VRNETLAB_PATH_CONTEXT
from engulf_clab_lab_parser import (
    TOPOLOGY_CONTEXT,
    TopologySession,
    is_topology_mutation_command,
)
from engulf_clab_vrnetlab_build_api import (
    VRNETLAB_BUILD_CONTEXT,
    VrnetlabBuildAPI,
    get_build_context,
)
from engulf_docker_image_api import (
    IMAGE_PROVIDER_CONTEXT,
    ImageProviderPlugin,
    RegisteredImageProvider,
    register_image_provider,
)
from engulf_executable_wrapper_api import (
    AfterCallEvent,
    ExecutableWrapperPlugin,
    PreparationFailedEvent,
    PreparedCallEvent,
)

from .errors import VrnetlabError
from .images import ensure_images
from .logging import use_logger
from .provider import VRNETLAB_PROVIDER_ID, VrnetlabBuildProvider
from .requests import build_requests_from_topology

PLUGIN_ID = "engulf_clab.vrnetlab_build"
DEFAULT_VRNETLAB_BUILD_JOBS = 2


class VrnetlabBuilderPlugin(ExecutableWrapperPlugin):
    """Build images for source paths published by active vrnetlab providers."""

    plugin_id = PLUGIN_ID
    priority = 78
    context_reads = frozenset(
        {
            VRNETLAB_PATH_CONTEXT,
            TOPOLOGY_CONTEXT,
            VRNETLAB_BUILD_CONTEXT,
            IMAGE_PROVIDER_CONTEXT,
        }
    )
    context_writes = frozenset({IMAGE_PROVIDER_CONTEXT})

    def __init__(self) -> None:
        self._provider = VrnetlabBuildProvider()

    def before_goal(
        self,
        invocation: Invocation,
        api: BeforeGoalAPI,
    ) -> GoalResult[object] | None:
        del invocation
        register_image_provider(
            api,
            RegisteredImageProvider(
                VRNETLAB_PROVIDER_ID,
                self._provider,
                priority=self.priority,
            ),
        )
        return None

    def prepare_call(self, event: PreparedCallEvent, api: InvocationAPI) -> None:
        if not is_topology_mutation_command(event.wrapper_args):
            return
        try:
            session = api.require_context(TOPOLOGY_CONTEXT)
            if not isinstance(session, TopologySession):
                raise VrnetlabError("invalid shared topology session")
            build_context = get_build_context(api)
            build_api = (
                None if build_context is None else VrnetlabBuildAPI(build_context)
            )
            requests = build_requests_from_topology(
                session.original_document(),
                event.environment,
                build_api,
            )
            checkout_context = api.get_context(VRNETLAB_PATH_CONTEXT)
            self._provider.refresh_requests(requests, checkout_context=checkout_context)
            if not requests:
                return

            max_workers = (
                DEFAULT_VRNETLAB_BUILD_JOBS
                if build_api is None or build_api.max_workers is None
                else build_api.max_workers
            )
            with use_logger(api.logger):
                ensure_images(
                    requests,
                    api=api,
                    checkout_context=checkout_context,
                    state_store=api.state(StateScope.USER),
                    max_workers=max_workers,
                )
        except (
            VrnetlabError,
            OSError,
            ValueError,
            TypeError,
            RuntimeError,
            subprocess.SubprocessError,
        ) as error:
            api.logger.error("%s", error)
            self._provider.clear()
            raise
        except BaseException:
            self._provider.clear()
            raise

    def prepare_failed(self, event: PreparationFailedEvent, api: InvocationAPI) -> None:
        del event, api
        self._provider.clear()

    def after_call(self, event: AfterCallEvent, api: InvocationAPI) -> None:
        del event, api
        self._provider.clear()


plugin = VrnetlabBuilderPlugin()
image_plugin = ImageProviderPlugin(
    VRNETLAB_PROVIDER_ID,
    plugin._provider,
    priority=VrnetlabBuilderPlugin.priority,
)
