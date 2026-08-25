from __future__ import annotations

from engulf_api import (
    BeforeGoalAPI,
    DependencyPosition,
    GoalResult,
    Invocation,
    InvocationAPI,
    PluginDependency,
)
from engulf_clab_containers_api import (
    CONTAINER_COLLECTION_CONTEXT,
    RegisteredContainerCollection,
)
from engulf_clab_lab_parser import (
    TOPOLOGY_CONTEXT,
    TopologySession,
    editor,
    load_topology,
    topology_path_from_args,
)
from engulf_clab_schema_api import (
    SCHEMA_CONTEXTS,
    SCHEMA_PLUGIN_DEPENDENCY,
    LifecycleStage,
    PluginSchema,
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

from .errors import ContainersError
from .manager import LABEL_PREFIX, catalog, format_catalog, topology_edits

_HELP_OPTION = "--eclab-containers-help"
PLUGIN_SCHEMA = (
    PluginSchema("engulf_clab.containers", package="engulf_clab_containers")
    .add_cli_flag(_HELP_OPTION, "List packaged containers from every active collection.")
    .add_node_prop(
        "image",
        "Select a packaged image as collection/name[:tag].",
        values=ValueType.IMAGE_REFERENCE,
    )
    .annotate(
        _HELP_OPTION,
        lifecycle=(LifecycleStage.ANALYZE_CALL,),
        implies=("wrapped Containerlab execution is preempted after printing the catalog",),
    )
    .annotate(
        "image",
        commands=("deploy",),
        lifecycle=(LifecycleStage.ANALYZE_CALL, LifecycleStage.PREPARE_CALL),
        requires=("an active container collection advertises the selected namespace/name",),
        shared_with=("eclab.containers",),
        examples=("eclab-containers/host-connector:latest",),
    )
    .use_case("Use a packaged helper container and inject its required node recipe.")
    .reject("Do not invent collection names; inspect the installed container catalog first.")
    .order(
        LifecycleStage.BEFORE_GOAL,
        "Collection registration precedes manager catalog discovery.",
        after=("eclab.containers",),
    )
    .order(
        LifecycleStage.PREPARE_CALL,
        "Recipe injection follows topology parsing and precedes builds and final serialization.",
        after=("engulf_clab.lab_parser",),
        before=("engulf_clab.dockerfile_build", "engulf_clab.lab_writer"),
    )
    .route(
        "use-packaged-container",
        "USAGE.md",
        "Read collection naming and recipe injection behavior.",
    )
    .refer("USAGE.md")
)


class ContainersPlugin(SchemaBackedPlugin):
    plugin_id = "engulf_clab.containers"
    schema = PLUGIN_SCHEMA
    priority = 85
    plugin_dependencies = (
        PluginDependency(
            "engulf_clab.lab_parser",
            preprocess=DependencyPosition.BEFORE,
            postprocess=None,
        ),
        PluginDependency(
            "engulf_clab.dockerfile_build",
            preprocess=DependencyPosition.AFTER,
            postprocess=None,
        ),
        PluginDependency(
            "engulf_clab.lab_writer",
            preprocess=DependencyPosition.AFTER,
            postprocess=None,
        ),
        SCHEMA_PLUGIN_DEPENDENCY,
    )
    context_reads = frozenset({CONTAINER_COLLECTION_CONTEXT, TOPOLOGY_CONTEXT}) | SCHEMA_CONTEXTS
    context_writes = SCHEMA_CONTEXTS

    def before_goal(self, invocation: Invocation, api: BeforeGoalAPI) -> GoalResult[object] | None:
        del invocation
        record_plugin_schema(api, PLUGIN_SCHEMA)
        self._collections(api)
        return None

    def help(self, api: HelpAPI) -> str:
        del api
        return (
            f"  {_HELP_OPTION}   List packaged containers from active collections\n"
            "  Select one as <collection-namespace>/<name>[:latest]; deploy injects its "
            "required node recipe."
        )

    def analyze_call(self, event: BeforeCallEvent, api: InvocationAPI) -> CallContribution | None:
        try:
            containers = catalog(self._collections(api))
            if _before_separator(event.wrapper_args, _HELP_OPTION):
                api.logger.warning("%s", format_catalog(containers))
                return CallContribution(preempt_exit_code=0)
            if (
                event.mode is CallMode.HELP
                or not event.wrapper_args
                or event.wrapper_args[0] != "deploy"
            ):
                return None
            path = topology_path_from_args(tuple(event.wrapper_args[1:]))
            topology_edits(load_topology(path), containers, prefix=LABEL_PREFIX)
        except (ContainersError, OSError, RuntimeError) as error:
            api.logger.error("%s", error)
            return CallContribution(preempt_exit_code=1)
        return None

    def prepare_call(self, event: PreparedCallEvent, api: InvocationAPI) -> None:
        if not event.wrapper_args or event.wrapper_args[0] != "deploy":
            return
        try:
            session = api.require_context(TOPOLOGY_CONTEXT)
            if not isinstance(session, TopologySession):
                raise ContainersError("invalid shared topology session")
            containers = catalog(self._collections(api))
            mutation = editor(api, self.plugin_id)
            document = session.original_document()
            nodes = document["topology"]["nodes"]
            for node_name, fields in topology_edits(document, containers, prefix=LABEL_PREFIX):
                original = nodes[node_name]
                for field, value in fields.items():
                    path = ("topology", "nodes", node_name, field)
                    if field in original:
                        if original[field] != value:
                            mutation.modify(path, value)
                    else:
                        mutation.add(path, value)
        except (ContainersError, OSError, RuntimeError) as error:
            api.logger.error("%s", error)
            raise

    @staticmethod
    def _collections(
        api: BeforeGoalAPI | InvocationAPI,
    ) -> tuple[RegisteredContainerCollection, ...]:
        value = api.get_context(CONTAINER_COLLECTION_CONTEXT, ())
        if type(value) is not tuple or any(
            not isinstance(item, RegisteredContainerCollection) for item in value
        ):
            raise ContainersError("invalid container collection registry")
        return value


def _before_separator(arguments: tuple[str, ...], option: str) -> bool:
    values = arguments[: arguments.index("--")] if "--" in arguments else arguments
    return option in values


plugin = ContainersPlugin()
