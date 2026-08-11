"""Reusable Containerlab application for Engulf extenders."""

from __future__ import annotations

import os
from os import PathLike
from pathlib import Path

from engulf import (
    Application,
    ApplicationDefinition,
    LoggingConfig,
    PluginPolicy,
    StateHomeResolver,
    WorkspaceRootResolver,
)
from engulf_executable_wrapper import ExecutableWrapperGoal
from engulf_executable_wrapper_api import (
    CallOutcome,
    CompletionCallable,
    CompletionProvider,
)

from .workspace import workspace_root

APPLICATION_ID = "engulf-clab"
DISPLAY_NAME = "engulf-clab"
VENDOR = "ECLAB"
PRODUCT = "Engulf Containerlab"
VERSION = "0.1.0"
CONTAINERLAB_BINARY = "containerlab"


def binary_path(binary: str = CONTAINERLAB_BINARY) -> str:
    """Return a configured Containerlab binary path or its PATH-resolved name."""
    if containerlab_dir := os.environ.get("CONTAINERLAB_DIR"):
        candidate = Path(containerlab_dir).expanduser() / binary
        if candidate.is_file():
            return str(candidate)
    return binary


def _containerlab_goal() -> ExecutableWrapperGoal:
    """Create the standard Containerlab goal when an application is launched."""
    return ExecutableWrapperGoal(binary_path())


# This definition is deliberately import-safe: editions can depend on this package
# and derive their own launcher without constructing an application or discovering
# plugins during import.  Editions retain ``APPLICATION_ID``, so they share the
# official plugin declaration group and persisted workspace state.
CONTAINERLAB_APPLICATION = ApplicationDefinition[CallOutcome](
    application_id=APPLICATION_ID,
    display_name=DISPLAY_NAME,
    goal_factory=_containerlab_goal,
    vendor=VENDOR,
    product=PRODUCT,
    version=VERSION,
    plugin_policy=PluginPolicy.declared(),
    workspace_root_resolver=workspace_root,
)


class ContainerlabApp(Application[CallOutcome]):
    """An extensible Engulf application with Containerlab defaults.

    Subclasses can override this constructor, pass different Engulf options, or add
    application-specific behavior while retaining Containerlab's workspace policy.
    """

    def __init__(
        self,
        binary: str | PathLike[str] | None = None,
        application_id: str = APPLICATION_ID,
        *,
        display_name: str = DISPLAY_NAME,
        vendor: str = VENDOR,
        product: str = PRODUCT,
        version: str = VERSION,
        logging_config: LoggingConfig | None = None,
        plugin_policy: PluginPolicy | None = None,
        plugin_dir: str | PathLike[str] | None = None,
        discover_installed: bool = True,
        completion_provider: CompletionCallable | CompletionProvider | None = None,
        workspace_root_resolver: WorkspaceRootResolver = workspace_root,
        state_home_resolver: StateHomeResolver | None = None,
    ) -> None:
        """Create the Containerlab executable-wrapper application.

        Without an explicit ``binary``, ``CONTAINERLAB_DIR/containerlab`` is used
        when present; otherwise Engulf resolves ``containerlab`` from ``PATH``.
        """
        executable = binary_path() if binary is None else binary
        executable_goal = ExecutableWrapperGoal(
            executable,
            completion_provider=completion_provider,
        )
        super().__init__(
            application_id,
            executable_goal,
            display_name=display_name,
            vendor=vendor,
            product=product,
            version=version,
            logging_config=logging_config,
            plugin_policy=(
                PluginPolicy.declared() if plugin_policy is None else plugin_policy
            ),
            plugin_dir=plugin_dir,
            discover_installed=discover_installed,
            workspace_root_resolver=workspace_root_resolver,
            state_home_resolver=state_home_resolver,
        )

    @property
    def binary(self) -> str:
        """Return the executable selected for this Containerlab application."""
        goal = self.goal
        assert isinstance(goal, ExecutableWrapperGoal)
        return goal.executable
