from __future__ import annotations

from engulf_api import (
    BeforeGoalAPI,
    GoalResult,
    Invocation,
    StateScope,
)
from engulf_executable_wrapper_api import (
    ExecutableWrapperPlugin,
    HelpAPI,
)

from .command import main as run_freeze_command


class FreezePlugin(ExecutableWrapperPlugin):
    """Own the freeze control command before the Containerlab goal runs."""

    plugin_id = "engulf_clab.freeze"
    priority = 200

    def before_goal(
        self, invocation: Invocation, api: BeforeGoalAPI
    ) -> GoalResult[object] | None:
        if not invocation.arguments or invocation.arguments[0] != "freeze":
            return None
        workspace = api.state(StateScope.WORKSPACE)
        offline = "--offline" in invocation.arguments[1:]
        application_name = (
            api.application.short_product_name or api.application.product
        )
        user_state = (
            api.state(StateScope.USER)
            if offline
            else None
        )
        # Fixed regardless of edition, so two differently-branded editions
        # freezing the same workspace concurrently actually block each other.
        leases = [f"eclab-freeze:{workspace.root}"]
        if offline:
            leases.extend(("repository-cache:containerlab", "repository-cache:vrnetlab"))
        with api.leases(tuple(leases)):
            exit_code = run_freeze_command(
                list(invocation.arguments[1:]),
                workspace,
                user_state=user_state,
                program=f"{application_name} freeze",
                application_name=application_name,
                logger=api.logger,
            )
        return GoalResult.completed(exit_code=exit_code)

    def help(self, api: HelpAPI) -> str:
        del api
        return (
            "  freeze [-t TOPOLOGY] [--output ARCHIVE] [--offline]  "
            "Create a sanitized portable lab archive"
        )
