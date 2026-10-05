from __future__ import annotations

import subprocess
from typing import Any

from engulf_api import (
    BeforeGoalAPI,
    GoalResult,
    Invocation,
    InvocationAPI,
)
from engulf_clab_ensure_vrnetlab import VRNETLAB_PATH_CONTEXT
from engulf_clab_lab_parser import (
    RUNTIME_TOPOLOGY_CONTEXT,
    TOPOLOGY_CONTEXT,
    TopologySession,
    effective_nodes,
    is_topology_mutation_command,
)
from engulf_clab_vrnetlab_build_api import (
    VRNETLAB_BUILD_CONTEXT,
    VRNETLAB_SOURCE_PROVENANCE_CONTEXT,
    VrnetlabBuildAPI,
    VrnetlabSourceProvenanceSnapshot,
    get_build_context,
    publish_vrnetlab_source_provenance,
    vrnetlab_source_provenance,
)
from engulf_docker_image_api import (
    IMAGE_PROVIDER_CONTEXT,
    ImageProviderPlugin,
    RegisteredImageProvider,
    register_image_provider,
)
from engulf_executable_wrapper_api import (
    AfterCallEvent,
    CallMode,
    ExecutableWrapperPlugin,
    OutcomeKind,
    PreparationFailedEvent,
    PreparedCallEvent,
)

from .errors import VrnetlabError
from .images import ensure_images
from .logging import use_logger
from .provenance import load_source_provenance, save_source_provenance
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
            RUNTIME_TOPOLOGY_CONTEXT,
            TOPOLOGY_CONTEXT,
            VRNETLAB_BUILD_CONTEXT,
            IMAGE_PROVIDER_CONTEXT,
            VRNETLAB_SOURCE_PROVENANCE_CONTEXT,
        }
    )
    context_writes = frozenset(
        {IMAGE_PROVIDER_CONTEXT, VRNETLAB_SOURCE_PROVENANCE_CONTEXT}
    )

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
        publish_vrnetlab_source_provenance(api, load_source_provenance(api))
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
                publish_vrnetlab_source_provenance(
                    api, VrnetlabSourceProvenanceSnapshot()
                )
                return

            max_workers = (
                DEFAULT_VRNETLAB_BUILD_JOBS
                if build_api is None or build_api.max_workers is None
                else build_api.max_workers
            )
            with use_logger(api.logger):
                provenance = ensure_images(
                    requests,
                    api=api,
                    checkout_context=checkout_context,
                    max_workers=max_workers,
                )
            publish_vrnetlab_source_provenance(api, provenance)
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
        try:
            if event.mode is CallMode.HELP or not event.wrapper_args:
                return
            if is_topology_mutation_command(event.wrapper_args):
                save_source_provenance(api, vrnetlab_source_provenance(api))
                return
            if (
                event.wrapper_args[0] == "inspect"
                and event.outcome.kind is OutcomeKind.COMPLETED
                and event.outcome.exit_code == 0
                and not any(
                    value in {"-a", "--all", "--name"}
                    or value.startswith("--name=")
                    for value in event.effective_args[1:]
                )
            ):
                session = api.get_context(RUNTIME_TOPOLOGY_CONTEXT, None)
                if isinstance(session, TopologySession):
                    _report_inspect_vrnetlab_provenance(
                        session.original_document(), vrnetlab_source_provenance(api), api
                    )
        finally:
            self._provider.clear()


def _report_inspect_vrnetlab_provenance(
    document: dict[str, Any],
    snapshot: VrnetlabSourceProvenanceSnapshot,
    api: InvocationAPI,
) -> None:
    records = []
    for node in effective_nodes(document):
        source = snapshot.source_for(node.name)
        if source is not None:
            image = node.data.get("image")
            records.append((source, image if isinstance(image, str) else "-"))
    if not records:
        return
    api.logger.info("vrnetlab image source provenance:")
    for source, image in records:
        if source.source_path is None:
            api.logger.info(
                "  node %s image=%s: builder=%s provider=%s source_sha256=%s",
                source.node_name,
                image,
                source.builder_type,
                source.source_provider_id or "external",
                source.source_sha256,
            )
        else:
            api.logger.info(
                "  node %s image=%s: builder=%s provider=%s source_path=%s "
                "source_sha256=%s",
                source.node_name,
                image,
                source.builder_type,
                source.source_provider_id or "external",
                source.source_path,
                source.source_sha256,
            )


plugin = VrnetlabBuilderPlugin()
image_plugin = ImageProviderPlugin(
    VRNETLAB_PROVIDER_ID,
    plugin._provider,
    priority=VrnetlabBuilderPlugin.priority,
)
