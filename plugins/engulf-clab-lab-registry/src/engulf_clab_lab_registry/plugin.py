from __future__ import annotations

from engulf_api import (
    AfterGoalAPI,
    BeforeGoalAPI,
    GoalResult,
    GoalResultStatus,
    Invocation,
    StateScope,
)
from engulf_clab_lab_parser import topology_path_from_args
from engulf_clab_lab_registry_api import (
    LAB_REGISTRY_COMMIT_CONTEXT,
    LAB_REGISTRY_CONTEXT,
    LabRecord,
    LabRegistryError,
    RegistryCommit,
)
from engulf_clab_schema_api import (
    SCHEMA_CONTEXTS,
    LifecycleStage,
    PluginSchema,
    Privilege,
    SchemaBackedPlugin,
    record_plugin_schema,
)
from engulf_executable_wrapper_api import HelpAPI

from .observe import observe_deployed_lab
from .storage import SessionLabRegistry, StateLabRegistry

PLUGIN_SCHEMA = (
    PluginSchema("engulf_clab.lab_registry", package="engulf_clab_lab_registry")
    .use_case("Maintain a shared inventory of deployed and explicitly discovered labs.")
    .order(
        LifecycleStage.BEFORE_GOAL,
        "The registry snapshot is published before inventory consumers run.",
        before=("engulf_clab.consumption", "engulf_clab.reclaim"),
    )
    .require_host_tool(
        "docker",
        "Successful deploy and redeploy observation reads Containerlab container metadata.",
        commands=("deploy", "redeploy"),
    )
    .require_privilege(
        Privilege.CONTAINER_RUNTIME,
        "Deployment observation requires read access to the configured container runtime.",
        commands=("deploy", "redeploy"),
    )
    .route(
        "understand-lab-inventory",
        "USAGE.md",
        "Read registry identity, observation, persistence, and retention behavior.",
    )
    .refer("USAGE.md")
    .require_host_tool("sudo", "Used when the caller cannot access the selected local Docker socket.")
)


class LabRegistryPlugin(SchemaBackedPlugin):
    """Publish the shared registry and observe successful lab deployments."""

    plugin_id = "engulf_clab.lab_registry"
    schema = PLUGIN_SCHEMA
    priority = 190
    context_reads = SCHEMA_CONTEXTS | frozenset(
        {LAB_REGISTRY_CONTEXT, LAB_REGISTRY_COMMIT_CONTEXT}
    )
    context_writes = SCHEMA_CONTEXTS | frozenset(
        {LAB_REGISTRY_CONTEXT, LAB_REGISTRY_COMMIT_CONTEXT}
    )

    def before_goal(
        self, invocation: Invocation, api: BeforeGoalAPI
    ) -> GoalResult[object] | None:
        del invocation
        record_plugin_schema(api, PLUGIN_SCHEMA)
        if api.get_context(LAB_REGISTRY_CONTEXT) is not None:
            raise RuntimeError("lab registry context is already published")
        # Load inside this plugin's own activation and publish the records, not
        # the store: readers run in their own callbacks, where a state handle
        # published here would already be deactivated.
        try:
            store = StateLabRegistry(api.state(StateScope.USER))
            session = SessionLabRegistry(store.records(), revision=store.revision())
        except (LabRegistryError, OSError) as problem:
            # An unreadable registry must not fail every command. Serve an empty
            # inventory and refuse to persist, so the unparsed file survives for
            # inspection instead of being overwritten.
            api.logger.warning("could not read lab registry: %s", problem)
            session = SessionLabRegistry(persistent=False)
        api.set_context(LAB_REGISTRY_CONTEXT, session)
        # The provider also consumes its publication so invocations with no
        # inventory reader do not report an unused-context diagnostic.
        api.get_context(LAB_REGISTRY_CONTEXT)
        return None

    def after_goal(
        self,
        invocation: Invocation,
        result: GoalResult[object],
        api: AfterGoalAPI,
    ) -> GoalResult[object]:
        session = api.get_context(LAB_REGISTRY_CONTEXT)
        if not isinstance(session, SessionLabRegistry):
            return result
        try:
            observed = self._observe(invocation, result)
            if observed is not None:
                session.upsert((observed,))
        except Exception as problem:  # noqa: BLE001 - inventory must not change the goal.
            api.logger.warning(
                "could not update lab registry after %s: %s",
                invocation.arguments[0] if invocation.arguments else "invocation",
                problem,
            )
        # Writes from every reader land here, in the one callback whose state
        # handle is live and owned by this plugin. The commit is fenced: it
        # merges each pending update against the entry as it is on disk now, so
        # a concurrent writer's newer record is never replaced by this session's
        # stale view. The outcome is published for destructive consumers that
        # ordered themselves to run later in this same phase.
        try:
            outcome = StateLabRegistry(api.state(StateScope.USER)).commit(session)
        except Exception as problem:  # noqa: BLE001 - inventory must not change the goal.
            outcome = RegistryCommit(committed=False, revision=session.revision, error=str(problem))
            api.logger.warning("could not persist lab registry: %s", problem)
        api.set_context(LAB_REGISTRY_COMMIT_CONTEXT, outcome)
        # Acknowledge the publication: most invocations have no consumer for it,
        # and an unread context would otherwise raise the unused-context
        # diagnostic on every non-reclaim command.
        api.get_context(LAB_REGISTRY_COMMIT_CONTEXT)
        return result

    @staticmethod
    def _observe(
        invocation: Invocation, result: GoalResult[object]
    ) -> LabRecord | None:
        """Return the record for a lab this invocation successfully deployed."""
        if (
            result.status is not GoalResultStatus.COMPLETED
            or result.exit_code != 0
            or not invocation.arguments
            or invocation.arguments[0] not in {"deploy", "redeploy"}
        ):
            return None
        topology = topology_path_from_args(
            tuple(invocation.arguments[1:]), invocation.cwd
        )
        return observe_deployed_lab(topology, invocation.environment)

    def help(self, api: HelpAPI) -> str:
        del api
        return (
            "  Lab registry (automatic)  Track deployed and explicitly discovered labs\n"
            "  Docker observation uses sudo when local socket access requires it."
        )
