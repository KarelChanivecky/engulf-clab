from __future__ import annotations

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
from engulf_docker_image_api import (
    IMAGE_GRAPH_CONTEXT,
    DockerfileRecipe,
    ImageBuildGraph,
    ImageProvision,
    ImageRequirement,
    append_image_graph,
)
from engulf_executable_wrapper_api import (
    BeforeCallEvent,
    CallContribution,
    CallMode,
    HelpAPI,
    PreparedCallEvent,
)

from .config import (
    BASE_NODE_ENV,
    LABEL_PREFIX,
    build_requests_from_topology,
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
    .add_node_var(
        BASE_NODE_ENV,
        "Build this node's image but omit the node from the derived deploy topology.",
        values=ValueType.BOOLEAN,
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
        BASE_NODE_ENV,
        commands=("deploy",),
        lifecycle=(LifecycleStage.ANALYZE_CALL, LifecycleStage.PREPARE_CALL),
        requires=("ECLAB_DOCKERFILE", "ECLAB_DOCKER_CTX", "node.image"),
        implies=(
            "the image remains a build root while the node is deleted from the derived topology",
        ),
        examples=(f'{BASE_NODE_ENV}: "true"',),
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
        "build-node-image", "USAGE.md", "Read Dockerfile pairing, path, tag, and argument rules."
    )
    .reject("Do not use --file or --tag in ECLAB_DOCKER_ARGS; the plugin owns them.")
    .order(
        LifecycleStage.PREPARE_CALL,
        "Dockerfile graph contribution follows topology mutation and precedes image resolution.",
        after=("engulf_clab.containers", "engulf_clab.lab_parser"),
        before=("engulf_clab.image_build", "engulf_clab.lab_writer"),
    )
    .refer("USAGE.md")
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
        PluginDependency(
            "engulf_clab.image_build",
            preprocess=DependencyPosition.AFTER,
            postprocess=None,
        ),
        SCHEMA_PLUGIN_DEPENDENCY,
    )
    context_reads = frozenset({TOPOLOGY_CONTEXT, IMAGE_GRAPH_CONTEXT}) | SCHEMA_CONTEXTS
    context_writes = frozenset({IMAGE_GRAPH_CONTEXT}) | SCHEMA_CONTEXTS

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
            f"    {BASE_NODE_ENV}  Build the image without deploying the node\n"
            "  The image-build dispatcher owns concurrency and recursive FROM resolution.\n"
            "  The node image field must resolve to a literal built tag during parsing; "
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
            build_requests_from_topology(
                topology_path,
                load_topology(topology_path, event.environment),
            )
        except (DockerfileError, OSError) as error:
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
            append_image_graph(
                api,
                ImageBuildGraph(
                    tuple(
                        ImageRequirement(
                            request.image,
                            origin=f"base topology node {request.node_name}",
                        )
                        for request in requests
                        if request.base_node
                    ),
                    tuple(
                        ImageProvision(
                            request.image,
                            DockerfileRecipe(
                                request.dockerfile,
                                request.context,
                                request.build_args,
                                request.extra_args,
                            ),
                            origin=f"topology node {request.node_name}",
                        )
                        for request in requests
                    ),
                ),
            )
            mutation = session.editor(self.plugin_id)
            for request in requests:
                if request.base_node:
                    mutation.delete(("topology", "nodes", request.node_name))
        except (DockerfileError, OSError, ValueError, TypeError, RuntimeError) as error:
            api.logger.error("%s", error)
            raise
