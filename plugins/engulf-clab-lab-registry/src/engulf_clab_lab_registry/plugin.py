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
from engulf_clab_lab_registry_api import LAB_REGISTRY_CONTEXT
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
from .storage import StateLabRegistry

PLUGIN_SCHEMA = (
    PluginSchema("engulf_clab.lab_registry", package="engulf_clab_lab_registry")
    .use_case("Maintain a shared inventory of deployed and explicitly discovered labs.")
    .order(
        LifecycleStage.BEFORE_GOAL,
        "The registry handle is published before inventory consumers run.",
        before=("engulf_clab.consumption",),
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
)


class LabRegistryPlugin(SchemaBackedPlugin):
    """Publish the shared registry and observe successful lab deployments."""

    plugin_id = "engulf_clab.lab_registry"
    schema = PLUGIN_SCHEMA
    priority = 190
    context_reads = SCHEMA_CONTEXTS | frozenset({LAB_REGISTRY_CONTEXT})
    context_writes = SCHEMA_CONTEXTS | frozenset({LAB_REGISTRY_CONTEXT})

    def before_goal(
        self, invocation: Invocation, api: BeforeGoalAPI
    ) -> GoalResult[object] | None:
        del invocation
        record_plugin_schema(api, PLUGIN_SCHEMA)
        if api.get_context(LAB_REGISTRY_CONTEXT) is not None:
            raise RuntimeError("lab registry context is already published")
        api.set_context(
            LAB_REGISTRY_CONTEXT,
            StateLabRegistry(api.state(StateScope.USER)),
        )
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
        if (
            result.status is not GoalResultStatus.COMPLETED
            or result.exit_code != 0
            or not invocation.arguments
            or invocation.arguments[0] not in {"deploy", "redeploy"}
        ):
            return result
        try:
            topology = topology_path_from_args(
                tuple(invocation.arguments[1:]), invocation.cwd
            )
            record = observe_deployed_lab(topology, invocation.environment)
            StateLabRegistry(api.state(StateScope.USER)).upsert((record,))
        except Exception as problem:  # noqa: BLE001 - inventory must not change the goal.
            api.logger.warning(
                "could not update lab registry after %s: %s",
                invocation.arguments[0],
                problem,
            )
        return result

    def help(self, api: HelpAPI) -> str:
        del api
        return (
            "  Lab registry (automatic)  Track deployed and explicitly discovered labs"
        )
