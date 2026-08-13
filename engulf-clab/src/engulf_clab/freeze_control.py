"""Managed workspace context for the optional ``eclab freeze`` command."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from engulf import Application, ApplicationDefinition, PluginPolicy
from engulf_api import (
    Goal,
    GoalAPI,
    GoalContract,
    GoalRequirement,
    GoalResult,
    Invocation,
    Plugin,
    StateScope,
    WorkspaceState,
)

_FREEZE_REQUIREMENT = GoalRequirement("org.engulf.clab.freeze", 1)

type FreezeCommand = Callable[[list[str], WorkspaceState], int]


class _FreezePlugin(Plugin):
    """Empty adapter type for a plugin-free internal control goal."""

    goal_requirement = _FREEZE_REQUIREMENT


class FreezeGoal(Goal[int]):
    """Run one optional command with the standard eclab workspace context."""

    _contract = GoalContract(_FREEZE_REQUIREMENT, _FreezePlugin)

    def __init__(self, command: FreezeCommand) -> None:
        self._command = command

    @property
    def contract(self) -> GoalContract:
        return self._contract

    def achieve(self, invocation: Invocation, api: GoalAPI) -> GoalResult[int]:
        workspace = api.state(StateScope.WORKSPACE)
        # Archive construction is long-running. A workspace-scoped lease keeps
        # concurrent freeze operations from copying one another's new archive.
        with api.leases((f"eclab-freeze:{workspace.root}",)):
            exit_code = self._command(list(invocation.arguments), workspace)
        return GoalResult.completed(exit_code=exit_code)


def run_freeze_command(
    definition: ApplicationDefinition[Any], command: FreezeCommand, arguments: Sequence[str]
) -> int:
    """Run a lazy freeze command without activating Containerlab plugins."""
    with Application(
        definition.application_id,
        FreezeGoal(command),
        display_name=definition.display_name,
        vendor=definition.vendor,
        product=definition.product,
        short_product_name=definition.short_product_name,
        version=definition.version,
        plugin_policy=PluginPolicy.allow_only(()),
        logging_config=definition.logging_config,
        discover_installed=False,
        workspace_root_resolver=definition.workspace_root_resolver,
        state_home_resolver=definition.state_home_resolver,
        diagnostic_isolation_config=definition.diagnostic_isolation_config,
    ) as application:
        return application.run(arguments)
