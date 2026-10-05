from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Mapping
from typing import Any

from engulf_api import (
    BeforeGoalAPI,
    GoalResult,
    Invocation,
    InvocationAPI,
    RegistrationAPI,
    StateScope,
)
from engulf_clab_lab_parser import (
    RUNTIME_TOPOLOGY_CONTEXT,
    TOPOLOGY_CONTEXT,
    TopologyError,
    TopologySession,
    editor,
    effective_nodes,
    is_topology_mutation_command,
)
from engulf_clab_schema_api import (
    SCHEMA_CONTEXTS,
    LifecycleStage,
    PluginSchema,
    Privilege,
    SchemaBackedPlugin,
    ValueType,
    record_plugin_schema,
)
from engulf_docker_image_api import (
    DOCKER_IMAGE_PROVENANCE_CONTEXT,
    IMAGE_GRAPH_CONTEXT,
    IMAGE_PROVIDER_CONTEXT,
    DockerImageProvenance,
    DockerImageProvenanceSnapshot,
    ImageBuildGraph,
    ImageParameter,
    ImageProvisionAction,
    ImageRequirement,
    ProvisionAuthority,
    docker_image_provenance,
    image_graphs,
    image_providers,
    publish_docker_image_provenance,
)
from engulf_docker_image_core import (
    DEFAULT_IMAGE_BUILD_JOBS,
    DockerImageError,
    ImageBuildOutcome,
    merge_image_graphs,
    provision_image_graph,
)
from engulf_executable_wrapper_api import (
    AfterCallEvent,
    ArgumentRegistry,
    BeforeCallEvent,
    CallContribution,
    CallMode,
    CompletionCandidate,
    CompletionContext,
    HelpAPI,
    Match,
    OutcomeKind,
    PreparedCallEvent,
    Runtime,
)

PLUGIN_ID = "engulf_clab.image_build"
IMAGE_BUILD_PLUGIN_ID = PLUGIN_ID
_VARIABLE_IMAGE = re.compile(r"\$(?:\$|\{?[A-Za-z_][A-Za-z0-9_]*)")
_JOBS_ENV = "ECLAB_IMAGE_BUILD_JOBS"
_LEGACY_JOBS_ENV = "ECLAB_DOCKER_BUILD_JOBS"
_JOBS_FLAG = "--eclab-image-build-jobs"
_LEGACY_JOBS_FLAG = "--eclab-docker-build-jobs"
_PARAMETER_PREFIX = "ECLAB_IMAGE_PARAM_"
_PROVENANCE_STATE_FILE = "docker-image-provenance.json"
_PROVENANCE_STATE_VERSION = 1

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
        commands=("deploy", "redeploy"),
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
        commands=("deploy", "redeploy"),
        lifecycle=(LifecycleStage.PREPARE_CALL,),
        requires=("node.image",),
        examples=("ECLAB_IMAGE_PARAM_RELEASE=2026.08",),
    )
    .annotate(
        _JOBS_ENV,
        commands=("deploy", "redeploy"),
        lifecycle=(LifecycleStage.ANALYZE_CALL, LifecycleStage.PREPARE_CALL),
    )
    .annotate(
        _LEGACY_JOBS_ENV,
        commands=("deploy", "redeploy"),
        lifecycle=(LifecycleStage.ANALYZE_CALL, LifecycleStage.PREPARE_CALL),
    )
    .annotate(
        _JOBS_FLAG,
        commands=("deploy", "redeploy"),
        lifecycle=(LifecycleStage.ANALYZE_CALL, LifecycleStage.PREPARE_CALL),
    )
    .require_host_tool(
        "docker", "Build provider-selected node images before deploy.", commands=("deploy", "redeploy")
    )
    .require_privilege(
        Privilege.CONTAINER_RUNTIME,
        "The caller must be authorized to use the configured Docker daemon.",
        commands=("deploy", "redeploy"),
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
    context_reads = (
        frozenset(
            {
                TOPOLOGY_CONTEXT,
                RUNTIME_TOPOLOGY_CONTEXT,
                IMAGE_PROVIDER_CONTEXT,
                IMAGE_GRAPH_CONTEXT,
                DOCKER_IMAGE_PROVENANCE_CONTEXT,
            }
        )
        | SCHEMA_CONTEXTS
    )
    context_writes = frozenset({DOCKER_IMAGE_PROVENANCE_CONTEXT}) | SCHEMA_CONTEXTS

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
            value_completer=Runtime(
                "image-build-jobs",
                _complete_image_build_jobs,
            ),
            when=Match.cursor_at(0) | Match.any_prior_word(("deploy", "redeploy")),
            environment=_JOBS_ENV,
        )

    def before_goal(self, invocation: Invocation, api: BeforeGoalAPI) -> GoalResult[object] | None:
        del invocation
        record_plugin_schema(api, PLUGIN_SCHEMA)
        image_providers(api)
        publish_docker_image_provenance(api, _load_image_provenance(api))
        return None

    def help(self, api: HelpAPI) -> str:
        del api
        return (
            "  Docker image providers are resolved recursively before deploy or redeploy.\n"
            "  Images and env parameters inherit defaults < kind < group < node.\n"
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
            or not is_topology_mutation_command(event.wrapper_args)
        ):
            return None
        try:
            image_build_jobs(event.environment)
        except ValueError as error:
            api.logger.error("%s", error)
            return CallContribution(preempt_exit_code=1)
        return None

    def prepare_call(self, event: PreparedCallEvent, api: InvocationAPI) -> None:
        if not is_topology_mutation_command(event.wrapper_args):
            return
        try:
            session = api.require_context(TOPOLOGY_CONTEXT)
            if not isinstance(session, TopologySession):
                raise DockerImageError("invalid shared topology session")
            document = session.materialize()
            roots = _topology_image_roots(document)
            fragments = (*image_graphs(api), ImageBuildGraph(roots))
            graph = merge_image_graphs(fragments)
            outcome = provision_image_graph(
                graph,
                api=api,
                providers=image_providers(api),
                max_workers=image_build_jobs(event.environment),
            )
            _force_local_root_policy(session, document, api)
            publish_docker_image_provenance(api, _image_provenance_snapshot(outcome))
        except (
            DockerImageError,
            OSError,
            ValueError,
            TypeError,
            subprocess.SubprocessError,
        ) as error:
            api.logger.error("%s", error)
            raise

    def after_call(self, event: AfterCallEvent, api: InvocationAPI) -> None:
        if event.mode is CallMode.HELP or not event.wrapper_args:
            return
        if is_topology_mutation_command(event.wrapper_args):
            _save_image_provenance(api, docker_image_provenance(api))
            return
        if (
            event.wrapper_args[0] != "inspect"
            or event.outcome.kind is not OutcomeKind.COMPLETED
            or event.outcome.exit_code != 0
            or any(
                value in {"-a", "--all", "--name"}
                or value.startswith("--name=")
                for value in event.effective_args[1:]
            )
        ):
            return
        session = api.get_context(RUNTIME_TOPOLOGY_CONTEXT, None)
        if not isinstance(session, TopologySession):
            return
        _report_inspect_provenance(api)


def _report_inspect_provenance(api: InvocationAPI) -> None:
    """Append persisted Docker provider attribution to a single-lab inspect."""
    snapshot = docker_image_provenance(api)
    records = sorted(snapshot.images, key=lambda record: record.image)
    if not records:
        return
    api.logger.info("Docker image provenance:")
    for record in records:
        api.logger.info(
            "  %s: provider=%s action=%s recipe=%s dependencies=%s",
            record.image,
            record.provider_id or "external",
            record.action.value,
            record.recipe_kind or "-",
            ", ".join(record.dependencies) or "-",
        )

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


def _image_provenance_snapshot(
    outcome: ImageBuildOutcome,
) -> DockerImageProvenanceSnapshot:
    """Publish provider attribution together with the completed execution result."""
    reused = frozenset(outcome.reused)
    pulled = frozenset(outcome.pulled)
    loaded = frozenset(outcome.loaded)
    built = frozenset(outcome.built)
    images = []
    for resolved in outcome.resolved.images:
        if resolved.external:
            action = ImageProvisionAction.EXTERNAL
        elif resolved.image in reused:
            action = ImageProvisionAction.REUSED
        elif resolved.image in pulled:
            action = ImageProvisionAction.PULLED
        elif resolved.image in loaded:
            action = ImageProvisionAction.LOADED
        elif resolved.image in built:
            action = ImageProvisionAction.BUILT
        else:
            raise DockerImageError(
                f"image provisioning completed without a recorded result for {resolved.image}"
            )
        images.append(
            DockerImageProvenance(
                image=resolved.image,
                provider_id=(
                    None if resolved.provider_id == "graph" else resolved.provider_id
                ),
                dependencies=resolved.dependencies,
                authority=resolved.authority if resolved.provision is not None else None,
                fallback_on_failure=(
                    resolved.fallback_on_failure if resolved.provision is not None else False
                ),
                action=action,
                recipe_kind=(
                    None
                    if resolved.provision is None
                    else resolved.provision.recipe.recipe_kind
                ),
            )
        )
    return DockerImageProvenanceSnapshot(tuple(images))


def _load_image_provenance(api: BeforeGoalAPI) -> DockerImageProvenanceSnapshot:
    state = api.state(StateScope.WORKSPACE)
    with state.transaction() as locked:
        if not locked.exists(_PROVENANCE_STATE_FILE):
            return DockerImageProvenanceSnapshot()
        try:
            document: Any = json.loads(locked.read_text(_PROVENANCE_STATE_FILE))
            if not isinstance(document, dict):
                raise TypeError("state root must be an object")
            if (
                type(document.get("version")) is not int
                or document.get("version") != _PROVENANCE_STATE_VERSION
            ):
                raise ValueError("state version is unsupported")
            values = document.get("images")
            if not isinstance(values, list):
                raise TypeError("state images must be a list")
            records = tuple(_image_provenance_from_state(value) for value in values)
            return DockerImageProvenanceSnapshot(records)
        except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError, ValueError) as error:
            api.logger.warning(
                "ignoring invalid Docker image provenance workspace state: %s", error
            )
            return DockerImageProvenanceSnapshot()


def _image_provenance_from_state(value: Any) -> DockerImageProvenance:
    if not isinstance(value, dict):
        raise TypeError("image provenance entry must be an object")
    image = value.get("image")
    provider_id = value.get("provider_id")
    recipe_kind = value.get("recipe_kind")
    dependencies = value.get("dependencies")
    authority_value = value.get("authority")
    fallback_on_failure = value.get("fallback_on_failure")
    action_value = value.get("action")
    if not isinstance(dependencies, list) or any(
        not isinstance(item, str) for item in dependencies
    ):
        raise ValueError("image provenance dependencies must be a list of strings")
    if authority_value is not None and type(authority_value) is not int:
        raise ValueError("image provenance authority must be an integer or null")
    return DockerImageProvenance(
        image=image,
        provider_id=provider_id,
        dependencies=tuple(dependencies),
        authority=(
            None if authority_value is None else ProvisionAuthority(authority_value)
        ),
        fallback_on_failure=fallback_on_failure,
        action=ImageProvisionAction(action_value),
        recipe_kind=recipe_kind,
    )


def _save_image_provenance(
    api: InvocationAPI, snapshot: DockerImageProvenanceSnapshot
) -> None:
    records = []
    for item in sorted(
        snapshot.images,
        key=lambda record: (
            record.image,
            record.provider_id or "",
            record.recipe_kind or "",
        ),
    ):
        records.append(
            {
                "image": item.image,
                "provider_id": item.provider_id,
                "recipe_kind": item.recipe_kind,
                "dependencies": list(item.dependencies),
                "authority": None if item.authority is None else int(item.authority),
                "fallback_on_failure": item.fallback_on_failure,
                "action": item.action.value,
            }
        )
    document = {"version": _PROVENANCE_STATE_VERSION, "images": records}
    state = api.state(StateScope.WORKSPACE)
    with state.transaction() as locked:
        locked.write_text(
            _PROVENANCE_STATE_FILE,
            json.dumps(document, sort_keys=True, indent=2) + "\n",
        )


def _deploy_completion(context: CompletionContext) -> bool:
    if context.cursor_index == 0:
        return True
    return bool({"deploy", "redeploy"}.intersection(context.words[: context.cursor_index]))


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
    try:
        resolved = effective_nodes(document)
    except TopologyError as error:
        raise DockerImageError(str(error)) from error
    for node in resolved:
        name = node.name
        image = node.data.get("image")
        if not isinstance(image, str) or not image.strip():
            continue
        if _VARIABLE_IMAGE.search(image):
            raise DockerImageError(
                f"node {name} image did not resolve to a literal for end-to-end provisioning: {image}"
            )
        environment = node.data.get("env", {})
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
    for node in effective_nodes(document):
        name = node.name
        image = node.data.get("image")
        if not isinstance(image, str) or not image.strip():
            continue
        if node.data.get("image-pull-policy") == "Never":
            continue
        path = ("topology", "nodes", name, "image-pull-policy")
        original = original_nodes.get(name)
        if isinstance(original, dict) and "image-pull-policy" in original:
            mutation.modify(path, "Never")
        else:
            mutation.add(path, "Never")


plugin = ImageBuildPlugin()
