from __future__ import annotations

import re
import subprocess
from collections.abc import Mapping
from typing import Any

from engulf_api import (
    BeforeGoalAPI,
    DependencyPosition,
    GoalResult,
    Invocation,
    InvocationAPI,
    PluginDependency,
    RegistrationAPI,
)
from engulf_clab_lab_parser import TOPOLOGY_CONTEXT, TopologySession, editor
from engulf_clab_schema_api import (
    SCHEMA_CONTEXTS,
    SCHEMA_PLUGIN_DEPENDENCY,
    LifecycleStage,
    PluginSchema,
    Privilege,
    SchemaBackedPlugin,
    ValueType,
    record_plugin_schema,
)
from engulf_docker_image_api import (
    IMAGE_GRAPH_CONTEXT,
    IMAGE_PROVIDER_CONTEXT,
    ImageBuildGraph,
    ImageParameter,
    ImageRequirement,
    image_graphs,
    image_providers,
)
from engulf_docker_image_core import (
    DEFAULT_IMAGE_BUILD_JOBS,
    DockerImageError,
    merge_image_graphs,
    provision_image_graph,
)
from engulf_executable_wrapper_api import (
    ArgumentRegistry,
    BeforeCallEvent,
    CallContribution,
    CallMode,
    CompletionCandidate,
    CompletionContext,
    HelpAPI,
    PreparedCallEvent,
)

PLUGIN_ID = "engulf_clab.image_build"
IMAGE_BUILD_PLUGIN_ID = PLUGIN_ID
_VARIABLE_IMAGE = re.compile(r"\$(?:\$|\{?[A-Za-z_][A-Za-z0-9_]*)")
_JOBS_ENV = "ECLAB_IMAGE_BUILD_JOBS"
_LEGACY_JOBS_ENV = "ECLAB_DOCKER_BUILD_JOBS"
_JOBS_FLAG = "--eclab-image-build-jobs"
_LEGACY_JOBS_FLAG = "--eclab-docker-build-jobs"
_PARAMETER_PREFIX = "ECLAB_IMAGE_PARAM_"

PLUGIN_SCHEMA = (
    PluginSchema(PLUGIN_ID, package="engulf_clab_image_build")
    .add_node_prop(
        "image",
        "Treat each literal deploy image as a root of the recursive provider build graph.",
        values=ValueType.IMAGE_REFERENCE,
    )
    .add_node_var(
        "ECLAB_IMAGE_PARAM_*",
        "Pass a custom parameter only to the provider for this node image.",
        values=ValueType.STRING,
    )
    .add_runtime_var(
        _JOBS_ENV,
        "Limit concurrent provider-backed Docker image builds.",
        values=ValueType.POSITIVE_INTEGER,
        default=DEFAULT_IMAGE_BUILD_JOBS,
    )
    .add_runtime_var(
        _LEGACY_JOBS_ENV,
        "Legacy fallback for concurrent Docker image builds.",
        values=ValueType.POSITIVE_INTEGER,
        deprecated=True,
        replacement=_JOBS_ENV,
    )
    .add_cli_flag(
        (_JOBS_FLAG, _LEGACY_JOBS_FLAG),
        "Limit concurrent provider-backed Docker image builds.",
        values=ValueType.POSITIVE_INTEGER,
        environment=_JOBS_ENV,
    )
    .annotate(
        "image",
        commands=("deploy",),
        lifecycle=(LifecycleStage.PREPARE_CALL,),
        implies=(
            "active providers are queried for the root and every statically discoverable literal Dockerfile FROM base",
            "selected recipes build dependency-first on every deploy and rely on Docker's layer cache",
            "unclaimed literal images use an exact local tag when present and otherwise use the low-authority Docker pull fallback",
            "the derived topology sets provisioned roots to image-pull-policy Never",
            "node images unresolved after parser expansion and dynamic FROM expressions fail before Containerlab runs",
        ),
    )
    .annotate(
        "ECLAB_IMAGE_PARAM_*",
        commands=("deploy",),
        lifecycle=(LifecycleStage.PREPARE_CALL,),
        requires=("node.image",),
        examples=("ECLAB_IMAGE_PARAM_RELEASE=2026.08",),
    )
    .annotate(
        _JOBS_ENV,
        commands=("deploy",),
        lifecycle=(LifecycleStage.ANALYZE_CALL, LifecycleStage.PREPARE_CALL),
    )
    .annotate(
        _LEGACY_JOBS_ENV,
        commands=("deploy",),
        lifecycle=(LifecycleStage.ANALYZE_CALL, LifecycleStage.PREPARE_CALL),
    )
    .annotate(
        _JOBS_FLAG,
        commands=("deploy",),
        lifecycle=(LifecycleStage.ANALYZE_CALL, LifecycleStage.PREPARE_CALL),
    )
    .require_host_tool(
        "docker", "Build provider-selected node images before deploy.", commands=("deploy",)
    )
    .require_privilege(
        Privilege.CONTAINER_RUNTIME,
        "The caller must be authorized to use the configured Docker daemon.",
        commands=("deploy",),
    )
    .use_case(
        "Build a deploy image whose literal Dockerfile FROM bases may also be supplied by active providers; resolution recurses before Containerlab runs."
    )
    .order(
        LifecycleStage.PREPARE_CALL,
        "Resolution follows topology mutation and graph contribution and precedes serialization.",
        after=("engulf_clab.lab_parser",),
        before=("engulf_clab.lab_writer",),
    )
    .route(
        "build-recursive-images",
        "USAGE.md",
        "Recursively request literal FROM bases from active providers and build selected dependencies before consumers.",
    )
    .route(
        "resolve-images",
        "USAGE.md",
        "Resolve a root image and every provider-buildable literal FROM dependency before deploy.",
    )
    .refer("USAGE.md")
)


class ImageBuildPlugin(SchemaBackedPlugin):
    plugin_id = PLUGIN_ID
    schema = PLUGIN_SCHEMA
    priority = 50
    plugin_dependencies = (
        PluginDependency(
            "engulf_clab.lab_parser",
            preprocess=DependencyPosition.BEFORE,
            postprocess=None,
        ),
        PluginDependency(
            "engulf_clab.lab_writer",
            preprocess=DependencyPosition.AFTER,
            postprocess=None,
        ),
        SCHEMA_PLUGIN_DEPENDENCY,
    )
    context_reads = (
        frozenset({TOPOLOGY_CONTEXT, IMAGE_PROVIDER_CONTEXT, IMAGE_GRAPH_CONTEXT}) | SCHEMA_CONTEXTS
    )
    context_writes = SCHEMA_CONTEXTS

    def register_arguments(
        self,
        registry: ArgumentRegistry,
        api: RegistrationAPI,
    ) -> None:
        del api
        registry.option(
            _JOBS_FLAG,
            _LEGACY_JOBS_FLAG,
            takes_value=True,
            metavar="POSITIVE_INTEGER",
            description="Limit concurrent provider-backed Docker image builds",
            value_completer=_complete_image_build_jobs,
            when=_deploy_completion,
            environment=_JOBS_ENV,
        )

    def before_goal(self, invocation: Invocation, api: BeforeGoalAPI) -> GoalResult[object] | None:
        del invocation
        record_plugin_schema(api, PLUGIN_SCHEMA)
        image_providers(api)
        return None

    def help(self, api: HelpAPI) -> str:
        del api
        return (
            "  Docker image providers are resolved recursively before deploy.\n"
            "  Unclaimed literal images use an exact local tag or pull when missing.\n"
            "  Provisioned roots use image-pull-policy Never in the derived topology.\n"
            "  Node YAML env fields:\n"
            "    ECLAB_IMAGE_PARAM_name  Parameter for this node image only\n"
            f"  {_JOBS_FLAG} COUNT  Concurrent image builds "
            f"(default: {DEFAULT_IMAGE_BUILD_JOBS})\n"
            f"  {_JOBS_ENV} is the persistent default; {_LEGACY_JOBS_FLAG} and "
            f"{_LEGACY_JOBS_ENV} remain compatibility aliases."
        )

    def analyze_call(self, event: BeforeCallEvent, api: InvocationAPI) -> CallContribution | None:
        if (
            event.mode is CallMode.HELP
            or not event.wrapper_args
            or event.wrapper_args[0] != "deploy"
        ):
            return None
        try:
            image_build_jobs(event.environment)
        except ValueError as error:
            api.logger.error("%s", error)
            return CallContribution(preempt_exit_code=1)
        return None

    def prepare_call(self, event: PreparedCallEvent, api: InvocationAPI) -> None:
        if not event.wrapper_args or event.wrapper_args[0] != "deploy":
            return
        try:
            session = api.require_context(TOPOLOGY_CONTEXT)
            if not isinstance(session, TopologySession):
                raise DockerImageError("invalid shared topology session")
            document = session.materialize()
            roots = _topology_image_roots(document)
            fragments = (*image_graphs(api), ImageBuildGraph(roots))
            graph = merge_image_graphs(fragments)
            provision_image_graph(
                graph,
                api=api,
                providers=image_providers(api),
                max_workers=image_build_jobs(event.environment),
            )
            _force_local_root_policy(session, document, api)
        except (
            DockerImageError,
            OSError,
            ValueError,
            TypeError,
            subprocess.SubprocessError,
        ) as error:
            api.logger.error("%s", error)
            raise


def image_build_jobs(environment: Mapping[str, str]) -> int:
    value = environment.get(_JOBS_ENV) or environment.get(_LEGACY_JOBS_ENV)
    if value is None:
        return DEFAULT_IMAGE_BUILD_JOBS
    try:
        jobs = int(value)
    except ValueError as error:
        raise ValueError(f"{_JOBS_ENV} must be a positive integer") from error
    if jobs < 1:
        raise ValueError(f"{_JOBS_ENV} must be a positive integer")
    return jobs


def _deploy_completion(context: CompletionContext) -> bool:
    if context.cursor_index == 0:
        return True
    return "deploy" in context.words[: context.cursor_index]


def _complete_image_build_jobs(
    context: CompletionContext,
) -> tuple[CompletionCandidate, ...]:
    default = str(DEFAULT_IMAGE_BUILD_JOBS)
    if default.startswith(context.current):
        return (CompletionCandidate(default, "Default value"),)
    return ()


def _topology_image_roots(document: dict[str, Any]) -> tuple[ImageRequirement, ...]:
    topology = document.get("topology")
    if not isinstance(topology, dict):
        raise DockerImageError("topology file is missing topology mapping")
    nodes = topology.get("nodes")
    if not isinstance(nodes, dict):
        raise DockerImageError("topology file is missing topology.nodes mapping")
    roots: list[ImageRequirement] = []
    for name, node in nodes.items():
        if not isinstance(node, dict):
            raise DockerImageError(f"node {name} must be a YAML mapping")
        image = node.get("image")
        if not isinstance(image, str) or not image.strip():
            continue
        if _VARIABLE_IMAGE.search(image):
            raise DockerImageError(
                f"node {name} image did not resolve to a literal for end-to-end provisioning: {image}"
            )
        environment = node.get("env", {})
        if not isinstance(environment, dict):
            raise DockerImageError(f"node {name} env must be a YAML mapping")
        parameters: dict[str, ImageParameter] = {}
        for key, value in environment.items():
            if not isinstance(key, str):
                continue
            if not key.startswith(_PARAMETER_PREFIX):
                continue
            parameter_name = key.removeprefix(_PARAMETER_PREFIX)
            if not parameter_name:
                raise DockerImageError(f"node {name} has an empty image parameter name")
            if not isinstance(value, str):
                raise DockerImageError(f"node {name} {key} must be a string")
            parameters[parameter_name] = ImageParameter(parameter_name, value)
        roots.append(
            ImageRequirement(
                image,
                tuple(parameters[key] for key in sorted(parameters)),
                origin=f"topology node {name}",
            )
        )
    return tuple(roots)


def _force_local_root_policy(
    session: TopologySession,
    document: dict[str, Any],
    api: InvocationAPI,
) -> None:
    topology = document.get("topology")
    original_topology = session.original_document().get("topology")
    if not isinstance(topology, dict) or not isinstance(original_topology, dict):
        raise DockerImageError("topology file is missing topology mapping")
    nodes = topology.get("nodes")
    original_nodes = original_topology.get("nodes")
    if not isinstance(nodes, dict) or not isinstance(original_nodes, dict):
        raise DockerImageError("topology file is missing topology.nodes mapping")
    mutation = editor(api, PLUGIN_ID)
    for name, node in nodes.items():
        if not isinstance(node, dict):
            continue
        image = node.get("image")
        if not isinstance(image, str) or not image.strip():
            continue
        if node.get("image-pull-policy") == "Never":
            continue
        path = ("topology", "nodes", name, "image-pull-policy")
        original = original_nodes.get(name)
        if isinstance(original, dict) and "image-pull-policy" in original:
            mutation.modify(path, "Never")
        else:
            mutation.add(path, "Never")


plugin = ImageBuildPlugin()
