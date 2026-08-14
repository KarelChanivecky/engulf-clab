from __future__ import annotations

from engulf_api import DependencyPosition, InvocationAPI, PluginDependency
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
from engulf_executable_wrapper_api import (
    BeforeCallEvent,
    CallContribution,
    CallMode,
    ExecutableWrapperPlugin,
    HelpAPI,
    PreparedCallEvent,
)

from .errors import ContainersError
from .manager import (
    application_prefix_name,
    catalog,
    environment_prefix,
    format_catalog,
    topology_edits,
)

_HELP_OPTION = "--eclab-containers-help"


class ContainersPlugin(ExecutableWrapperPlugin):
    plugin_id = "engulf_clab.containers"
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
    )
    context_reads = frozenset({CONTAINER_COLLECTION_CONTEXT, TOPOLOGY_CONTEXT})

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
            prefix = environment_prefix(application_prefix_name(api.application))
            topology_edits(load_topology(path), containers, prefix=prefix)
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
            prefix = environment_prefix(application_prefix_name(api.application))
            mutation = editor(api, self.plugin_id)
            document = session.original_document()
            nodes = document["topology"]["nodes"]
            for node_name, fields in topology_edits(document, containers, prefix=prefix):
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
    def _collections(api: InvocationAPI) -> tuple[RegisteredContainerCollection, ...]:
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
