from __future__ import annotations

import subprocess

from engulf_api import DependencyPosition, InvocationAPI, PluginDependency
from engulf_clab_lab_parser import TOPOLOGY_CONTEXT, TopologySession
from engulf_executable_wrapper_api import (
    BeforeCallEvent,
    CallContribution,
    CallMode,
    ExecutableWrapperPlugin,
    HelpAPI,
    PreparedCallEvent,
)

from .build import build_images
from .config import application_prefix_name, build_requests_from_topology, environment_prefix
from .errors import DockerfileError
from .topology import load_topology, topology_path_from_args


class DockerfilePlugin(ExecutableWrapperPlugin):
    plugin_id = "engulf_clab.dockerfile_build"
    priority = 70
    plugin_dependencies = (
        PluginDependency(
            "engulf_clab.lab_parser",
            preprocess=DependencyPosition.BEFORE,
            postprocess=None,
        ),
    )
    context_reads = frozenset({TOPOLOGY_CONTEXT})

    def help(self, api: HelpAPI) -> str:
        prefix = environment_prefix(application_prefix_name(api.application))
        return (
            "  Node YAML env fields (paths are relative to the topology file):\n"
            f"    {prefix}_DOCKERFILE       Dockerfile; requires {prefix}_DOCKER_CTX\n"
            f"    {prefix}_DOCKER_CTX       Docker build-context directory\n"
            f"    {prefix}_DOCKER_VAR_name  Pass Docker --build-arg name=value\n"
            f"    {prefix}_DOCKER_ARGS      Additional docker build arguments\n"
            "  The node image field is the built tag; --file and --tag are reserved."
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
            build_requests_from_topology(
                topology_path,
                load_topology(topology_path),
                application_name=application_prefix_name(api.application),
            )
        except (DockerfileError, OSError, subprocess.SubprocessError) as error:
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
            if not isinstance(session, TopologySession): raise DockerfileError("invalid shared topology session")
            requests = build_requests_from_topology(
                topology_path,
                session.original_document(),
                application_name=application_prefix_name(api.application),
            )
            build_images(requests, api=api)
        except (DockerfileError, OSError, subprocess.SubprocessError) as error:
            api.logger.error("%s", error)
            raise
