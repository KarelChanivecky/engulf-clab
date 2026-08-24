from __future__ import annotations

import subprocess

from engulf_api import (
    BeforeGoalAPI,
    DependencyPosition,
    GoalResult,
    Invocation,
    InvocationAPI,
    PluginDependency,
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
from engulf_executable_wrapper_api import (
    BeforeCallEvent,
    CallContribution,
    CallMode,
    HelpAPI,
    PreparedCallEvent,
)

from .build import build_images
from .config import (
    DEFAULT_DOCKER_BUILD_JOBS,
    LABEL_PREFIX,
    build_requests_from_topology,
    docker_build_jobs,
)
from .errors import DockerfileError
from .topology import load_topology, topology_path_from_args

PLUGIN_SCHEMA = (
    PluginSchema("engulf_clab.dockerfile_build", package="engulf_clab_dockerfile_build")
    .add_node_var(
        "ECLAB_DOCKERFILE",
        "Set the Dockerfile path relative to the topology file.",
        values=ValueType.FILE_PATH,
    )
    .add_node_var(
        "ECLAB_DOCKER_CTX",
        "Set the Docker build-context directory relative to the topology file.",
        values=ValueType.DIRECTORY_PATH,
    )
    .add_node_var(
        "ECLAB_DOCKER_VAR_*",
        "Pass the wildcard suffix as a Docker build-argument name.",
        values=ValueType.STRING,
    )
    .add_node_var(
        "ECLAB_DOCKER_ARGS", "Pass additional Docker build arguments.", values=ValueType.STRING
    )
    .add_runtime_var(
        "ECLAB_DOCKER_BUILD_JOBS",
        "Limit concurrent Docker image builds; the matching CLI flag takes precedence.",
        values=ValueType.POSITIVE_INTEGER,
        default=2,
    )
    .add_cli_flag(
        "--eclab-docker-build-jobs",
        "Limit concurrent Docker image builds.",
        values=ValueType.POSITIVE_INTEGER,
        environment="ECLAB_DOCKER_BUILD_JOBS",
    )
    .annotate(
        "ECLAB_DOCKERFILE",
        commands=("deploy",),
        lifecycle=(LifecycleStage.ANALYZE_CALL, LifecycleStage.PREPARE_CALL),
        requires=("ECLAB_DOCKER_CTX", "node.image is the literal output tag"),
        path_base=PathBase.TOPOLOGY_DIRECTORY,
        host_tools=("docker",),
        examples=("api/Dockerfile",),
    )
    .annotate(
        "ECLAB_DOCKER_CTX",
        commands=("deploy",),
        requires=("ECLAB_DOCKERFILE",),
        path_base=PathBase.TOPOLOGY_DIRECTORY,
        examples=("api",),
    )
    .annotate(
        "ECLAB_DOCKER_VAR_*",
        commands=("deploy",),
        requires=("ECLAB_DOCKERFILE", "ECLAB_DOCKER_CTX"),
        examples=("ECLAB_DOCKER_VAR_VERSION=1.2.3",),
    )
    .annotate(
        "ECLAB_DOCKER_ARGS",
        commands=("deploy",),
        requires=("ECLAB_DOCKERFILE", "ECLAB_DOCKER_CTX"),
        conflicts_with=("Docker flags --file and --tag",),
    )
    .annotate(
        "ECLAB_DOCKER_BUILD_JOBS",
        commands=("deploy",),
        lifecycle=(LifecycleStage.ANALYZE_CALL, LifecycleStage.PREPARE_CALL),
    )
    .annotate(
        "--eclab-docker-build-jobs",
        commands=("deploy",),
        lifecycle=(LifecycleStage.ANALYZE_CALL, LifecycleStage.PREPARE_CALL),
    )
    .require_host_tool(
        "docker", "Build node images before Containerlab deploys them.", commands=("deploy",)
    )
    .require_privilege(
        Privilege.CONTAINER_RUNTIME,
        "The caller must be authorized to use the configured Docker daemon.",
        commands=("deploy",),
    )
    .use_case("Build a node image from a topology-relative Dockerfile and context before deploy.")
    .route(
        "build-node-image", "README.md", "Read Dockerfile pairing, path, tag, and argument rules."
    )
    .reject("Do not use --file or --tag in ECLAB_DOCKER_ARGS; the plugin owns them.")
    .order(
        LifecycleStage.PREPARE_CALL,
        "Image builds consume parsed topology after packaged recipes are injected and before serialization.",
        after=("engulf_clab.containers", "engulf_clab.lab_parser"),
        before=("engulf_clab.lab_writer",),
    )
    .refer("README.md")
    .refer("AGENTS.md")
)


class DockerfilePlugin(SchemaBackedPlugin):
    plugin_id = "engulf_clab.dockerfile_build"
    schema = PLUGIN_SCHEMA
    priority = 70
    plugin_dependencies = (
        PluginDependency(
            "engulf_clab.lab_parser",
            preprocess=DependencyPosition.BEFORE,
            postprocess=None,
        ),
        SCHEMA_PLUGIN_DEPENDENCY,
    )
    context_reads = frozenset({TOPOLOGY_CONTEXT}) | SCHEMA_CONTEXTS
    context_writes = SCHEMA_CONTEXTS

    def before_goal(self, invocation: Invocation, api: BeforeGoalAPI) -> GoalResult[object] | None:
        del invocation
        record_plugin_schema(api, PLUGIN_SCHEMA)
        return None

    def help(self, api: HelpAPI) -> str:
        del api
        prefix = LABEL_PREFIX
        return (
            "  Node YAML env fields (paths are relative to the topology file):\n"
            f"    {prefix}_DOCKERFILE       Dockerfile; requires {prefix}_DOCKER_CTX\n"
            f"    {prefix}_DOCKER_CTX       Docker build-context directory\n"
            f"    {prefix}_DOCKER_VAR_name  Pass Docker --build-arg name=value\n"
            f"    {prefix}_DOCKER_ARGS      Additional docker build arguments\n"
            "  Wrapper option:\n"
            "    --eclab-docker-build-jobs COUNT  Concurrent image builds "
            f"(default: {DEFAULT_DOCKER_BUILD_JOBS})\n"
            f"  {prefix}_DOCKER_BUILD_JOBS is the persistent environment default; "
            "the CLI option wins.\n"
            "  The node image field is the literal built tag; variables are unsupported; "
            "--file and --tag are reserved."
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
            build_requests_from_topology(topology_path, load_topology(topology_path))
            docker_build_jobs(event.environment)
        except (DockerfileError, OSError, subprocess.SubprocessError) as error:
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
                raise DockerfileError("invalid shared topology session")
            topology_path = session.path
            requests = build_requests_from_topology(topology_path, session.materialize())
            build_images(
                requests,
                api=api,
                max_workers=docker_build_jobs(event.environment),
            )
        except (DockerfileError, OSError, subprocess.SubprocessError) as error:
            api.logger.error("%s", error)
            raise
