from __future__ import annotations

from engulf_api import (
    BeforeGoalAPI,
    GoalResult,
    Invocation,
    InvocationAPI,
)
from engulf_clab_lab_parser import (
    TOPOLOGY_CONTEXT,
    TopologySession,
    is_topology_mutation_command,
)
from engulf_clab_schema_api import (
    SCHEMA_CONTEXTS,
    LifecycleStage,
    PathBase,
    PluginSchema,
    Privilege,
    SchemaBackedPlugin,
    ValueType,
    record_plugin_schema,
)
from engulf_docker_image_api import (
    IMAGE_PROVIDER_CONTEXT,
    ImageProviderPlugin,
    RegisteredImageProvider,
    register_image_provider,
)
from engulf_executable_wrapper_api import (
    AfterCallEvent,
    BeforeCallEvent,
    CallContribution,
    CallMode,
    HelpAPI,
    PreparationFailedEvent,
    PreparedCallEvent,
)

from .config import (
    ARCHIVE_ENV,
    ARCHIVE_REF_ENV,
    ARCHIVE_RELOAD_ENV,
    build_requests_from_topology,
)
from .errors import ImageArchiveError
from .provider import ARCHIVE_PROVIDER_ID, ImageArchiveProvider
from .topology import load_topology, topology_path_from_args

PLUGIN_ID = "engulf_clab.image_archive"

PLUGIN_SCHEMA = (
    PluginSchema(PLUGIN_ID, package="engulf_clab_image_archive")
    .add_node_var(
        ARCHIVE_ENV,
        "Create this node's image by loading a saved Docker image archive.",
        values=ValueType.FILE_PATH,
    )
    .add_node_var(
        ARCHIVE_REF_ENV,
        "Select which reference inside the archive is retagged as the node image.",
        values=ValueType.IMAGE_REFERENCE,
    )
    .add_node_var(
        ARCHIVE_RELOAD_ENV,
        "Load the archive on every deploy instead of accepting an existing local tag.",
        values=ValueType.BOOLEAN,
        default=False,
    )
    .annotate(
        ARCHIVE_ENV,
        commands=("deploy", "redeploy"),
        lifecycle=(LifecycleStage.ANALYZE_CALL, LifecycleStage.PREPARE_CALL),
        requires=("node.image is the literal tag the archive is loaded as",),
        path_base=PathBase.TOPOLOGY_DIRECTORY,
        implies=(
            "the archive is a docker save stream, optionally gzip, bzip2, or xz compressed",
            "a single-image archive is retagged as the node image when it carries another tag",
        ),
        examples=("images/router.tar.gz",),
    )
    .annotate(
        ARCHIVE_REF_ENV,
        commands=("deploy", "redeploy"),
        lifecycle=(LifecycleStage.ANALYZE_CALL, LifecycleStage.PREPARE_CALL),
        requires=(ARCHIVE_ENV,),
        implies=("required when a multi-image archive does not carry the node image",),
        examples=("vendor/router:1.0.0",),
    )
    .annotate(
        ARCHIVE_RELOAD_ENV,
        commands=("deploy", "redeploy"),
        lifecycle=(LifecycleStage.ANALYZE_CALL, LifecycleStage.PREPARE_CALL),
        requires=(ARCHIVE_ENV,),
        examples=(f'{ARCHIVE_RELOAD_ENV}: "true"',),
    )
    .require_host_tool(
        "docker", "Load node image archives before Containerlab deploys them.", commands=("deploy", "redeploy")
    )
    .require_privilege(
        Privilege.CONTAINER_RUNTIME,
        "The caller must be authorized to use the configured Docker daemon.",
        commands=("deploy", "redeploy"),
    )
    .use_case("Create a node image from a saved Docker image archive shipped beside the lab.")
    .reject("Do not point this at a qcow2 or raw disk image; that is a vrnetlab source.")
    .order(
        LifecycleStage.PREPARE_CALL,
        "Archive provider registration follows topology mutation and precedes image resolution.",
        after=("engulf_clab.lab_parser",),
        before=("engulf_clab.image_build", "engulf_clab.lab_writer"),
    )
    .route(
        "load-image-archive",
        "USAGE.md",
        "Read archive selection, retag, reload, and troubleshooting rules.",
    )
    .refer("USAGE.md")
)


class ImageArchivePlugin(SchemaBackedPlugin):
    plugin_id = PLUGIN_ID
    schema = PLUGIN_SCHEMA
    priority = 72
    context_reads = frozenset({TOPOLOGY_CONTEXT, IMAGE_PROVIDER_CONTEXT}) | SCHEMA_CONTEXTS
    # register_image_provider appends to the provider registry, so registration is a
    # read-modify-write of IMAGE_PROVIDER_CONTEXT — it must appear in both sets.
    context_writes = frozenset({IMAGE_PROVIDER_CONTEXT}) | SCHEMA_CONTEXTS

    def __init__(self) -> None:
        self._provider = ImageArchiveProvider()

    def before_goal(self, invocation: Invocation, api: BeforeGoalAPI) -> GoalResult[object] | None:
        del invocation
        record_plugin_schema(api, PLUGIN_SCHEMA)
        register_image_provider(
            api,
            RegisteredImageProvider(ARCHIVE_PROVIDER_ID, self._provider, priority=self.priority),
        )
        return None

    def help(self, api: HelpAPI) -> str:
        del api
        return (
            "  Node YAML env fields (paths are relative to the topology file):\n"
            "    Values inherit defaults < kind < group < node.\n"
            f"    {ARCHIVE_ENV}         Saved Docker image archive to load\n"
            f"    {ARCHIVE_REF_ENV}     Archive reference retagged as the node image\n"
            f"    {ARCHIVE_RELOAD_ENV}  Load again even when the tag exists locally\n"
            "  The archive is a docker save stream (.tar, .tar.gz, .tgz, .tar.bz2, "
            ".tbz2, .tar.xz, or .txz).\n"
            "  This plugin's provider offers a load recipe for the node image tag ahead "
            "of the pull fallback; a failed load is reported instead of pulling that tag.\n"
            "  The node image field must resolve to a literal tag during parsing."
        )

    def analyze_call(self, event: BeforeCallEvent, api: InvocationAPI) -> CallContribution | None:
        if event.mode is CallMode.HELP or not event.wrapper_args:
            return None
        _command, *rest = event.wrapper_args
        if not is_topology_mutation_command(event.wrapper_args):
            return None
        try:
            topology_path = topology_path_from_args(tuple(rest))
            build_requests_from_topology(
                topology_path,
                load_topology(topology_path, event.environment),
            )
        except (ImageArchiveError, OSError) as error:
            api.logger.error("%s", error)
            return CallContribution(preempt_exit_code=1)
        return None

    def prepare_call(self, event: PreparedCallEvent, api: InvocationAPI) -> None:
        if not is_topology_mutation_command(event.wrapper_args):
            return
        try:
            session = api.require_context(TOPOLOGY_CONTEXT)
            if not isinstance(session, TopologySession):
                raise ImageArchiveError("invalid shared topology session")
            requests = build_requests_from_topology(session.path, session.materialize())
            # Populate the provider map before engulf_clab.image_build — which runs
            # after this prepare_call — resolves the topology image roots, so these
            # references reach the archive recipe instead of the pull fallback.
            self._provider.refresh_requests(requests)
            for request in requests:
                api.logger.debug(
                    "node %s provisions %s from %s",
                    request.node_name,
                    request.image,
                    request.archive,
                )
        except (ImageArchiveError, OSError, ValueError, TypeError, RuntimeError) as error:
            api.logger.error("%s", error)
            self._provider.clear()
            raise
        except BaseException:
            # This plugin does not receive prepare_failed when its own callback
            # raises. BaseException rather than Exception, so an interrupt cannot
            # leave a stale reference map on the singleton either.
            self._provider.clear()
            raise

    def prepare_failed(self, event: PreparationFailedEvent, api: InvocationAPI) -> None:
        del event, api
        self._provider.clear()

    def after_call(self, event: AfterCallEvent, api: InvocationAPI) -> None:
        del event, api
        self._provider.clear()


plugin = ImageArchivePlugin()

# Adapter exposed under the org_engulf_docker_image goal entry point. It wraps the SAME
# provider instance as `plugin` so references recorded by plugin.prepare_call are the
# ones provide() answers for, whichever dispatch path drives resolution.
image_plugin = ImageProviderPlugin(
    ARCHIVE_PROVIDER_ID, plugin._provider, priority=ImageArchivePlugin.priority
)
