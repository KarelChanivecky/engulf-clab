"""Reusable Containerlab application for Engulf extenders."""

from __future__ import annotations

import importlib.metadata
import os
import sys
from collections.abc import Iterable, Mapping
from os import PathLike
from pathlib import Path
from typing import Any

from engulf import (
    Application,
    ApplicationDefinition,
    LoggingConfig,
    PluginPolicy,
    StateHomeResolver,
    WorkspaceRootResolver,
)
from engulf_executable_wrapper import (
    CompiledCompletion,
    CompletionArtifactStore,
    ExecutableWrapperGoal,
    compile_completion,
    completion_environment_fingerprint,
)
from engulf_executable_wrapper_api import (
    CallOutcome,
    CompletionCallable,
    CompletionProvider,
)

from .workspace import workspace_root

APPLICATION_ID = "engulf-clab"
DISPLAY_NAME = "eclab"
VENDOR = "ECLAB"
PRODUCT = "Engulf Containerlab"
SHORT_PRODUCT_NAME = "eclab"


def _distribution_version() -> str:
    """Report the installed distribution version rather than a second copy of it.

    A hand-maintained constant drifts from `pyproject.toml` silently, and the
    reported version is what identifies a build in a bug report.
    """
    try:
        return importlib.metadata.version("engulf-clab")
    except importlib.metadata.PackageNotFoundError:
        # Running from a source tree that was never installed.
        return "0+unknown"


VERSION = _distribution_version()
CONTAINERLAB_BINARY = "containerlab"


def completion_artifact_path(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return the per-user persisted completion artifact location."""
    values = os.environ if environment is None else environment
    cache_home = values.get("XDG_CACHE_HOME")
    if cache_home is None:
        home = values.get("HOME")
        if not home:
            raise ValueError("HOME is required to locate the completion artifact")
        cache_home = str(Path(home).expanduser() / ".cache")
    cache = Path(cache_home).expanduser()
    if not cache.is_absolute():
        raise ValueError("XDG_CACHE_HOME must be an absolute path")
    return cache / APPLICATION_ID / "completion.json"


def completion_installed_metadata() -> dict[str, object]:
    """Capture import-free installed inputs that invalidate completion."""
    groups = {
        "engulf.plugins.v1.application.engulf_clab",
        "engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper",
    }
    entries: Iterable[Any]
    try:
        entries = importlib.metadata.entry_points()
    except (ImportError, OSError, TypeError, ValueError):
        entries = ()
    records: list[dict[str, object]] = []
    for entry in entries:
        if entry.group not in groups and not entry.group.startswith(
            "engulf.plugins.v1.dependency."
        ):
            continue
        distribution = entry.dist
        if distribution is None:
            distribution_record: dict[str, object] = {}
        else:
            try:
                files = tuple(sorted(str(item) for item in (distribution.files or ())))
            except (OSError, TypeError, ValueError):
                files = ()
            record_stats: list[tuple[str, int, int]] = []
            for item in files:
                if not item.endswith(".dist-info/RECORD"):
                    continue
                try:
                    stat = Path(str(distribution.locate_file(item))).stat()
                except (OSError, RuntimeError, TypeError, ValueError):
                    continue
                record_stats.append((item, stat.st_mtime_ns, stat.st_size))
            distribution_record = {
                "name": distribution.name,
                "version": distribution.version,
                "files": files,
                "record_stats": tuple(record_stats),
            }
        records.append(
            {
                "group": entry.group,
                "name": entry.name,
                "value": entry.value,
                "distribution": distribution_record,
            }
        )
    return {
        "application_id": APPLICATION_ID,
        "display_name": DISPLAY_NAME,
        "short_product_name": SHORT_PRODUCT_NAME,
        "binary": binary_path(),
        "containerlab_dir": os.environ.get("CONTAINERLAB_DIR"),
        "framework": {
            name: importlib.metadata.version(name)
            for name in (
                "engulf",
                "engulf-api",
                "engulf-executable-wrapper",
                "engulf-executable-wrapper-api",
            )
        },
        "entry_points": sorted(
            records,
            key=lambda item: (
                str(item["group"]),
                str(item["name"]),
                str(item["value"]),
            ),
        ),
    }


def load_completion_artifact() -> tuple[CompiledCompletion, str] | None:
    """Load the current manifest and its fingerprint without activating plugins."""
    metadata = completion_installed_metadata()
    fingerprint = completion_environment_fingerprint(metadata)
    manifest = CompletionArtifactStore().load(
        completion_artifact_path(), fingerprint=fingerprint
    )
    if manifest is None:
        return None
    return CompiledCompletion.from_manifest(manifest, {}), fingerprint


def publish_completion_artifact(application: Application[CallOutcome]) -> CompiledCompletion:
    """Compile setup declarations with Engulf's resolved orders and publish them."""
    goal = application.goal
    if not isinstance(goal, ExecutableWrapperGoal):
        raise TypeError("Containerlab application goal is not an executable wrapper")
    dependencies = {
        plugin.plugin_id: tuple(dependency.plugin_id for dependency in plugin.dependencies)
        for plugin in application.active_plugins
    }
    compiled = compile_completion(
        goal.arguments,
        goal.completions,
        dependencies=dependencies,
        preprocess_order=tuple(plugin.plugin_id for plugin in application.active_plugins),
        postprocess_order=tuple(
            plugin.plugin_id for plugin in application.postprocess_plugins
        ),
    )
    goal.replace_compiled_completion(compiled)
    metadata = completion_installed_metadata()
    CompletionArtifactStore().publish(
        completion_artifact_path(),
        compiled.manifest,
        fingerprint=completion_environment_fingerprint(metadata),
    )
    return compiled


def binary_path(binary: str = CONTAINERLAB_BINARY) -> str:
    """Return a configured Containerlab binary path or its PATH-resolved name."""
    if containerlab_dir := os.environ.get("CONTAINERLAB_DIR"):
        candidate = Path(containerlab_dir).expanduser() / binary
        if candidate.is_file():
            return str(candidate)
    if companion := _companion_binary(binary):
        return companion
    return binary


def _companion_binary(binary: str) -> str | None:
    """Return a binary installed beside this console script, if there is one.

    An environment that has Containerlab next to `eclab` works when the venv is
    activated and fails with `command not found` when it is not, purely because
    the directory is off PATH. The interpreter running this process is already in
    that directory, so resolve against it rather than depending on activation.
    """
    # Deliberately not resolved: a venv's python is usually a symlink to the
    # system interpreter, and following it would leave the environment and pick
    # up an unrelated system binary instead of the companion one.
    candidate = Path(sys.executable).parent / binary
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return None


def _containerlab_goal() -> ExecutableWrapperGoal:
    """Create the standard Containerlab goal when an application is launched."""
    return ExecutableWrapperGoal(binary_path(), source_completion=True)


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
    short_product_name=SHORT_PRODUCT_NAME,
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
        short_product_name: str = SHORT_PRODUCT_NAME,
        version: str = VERSION,
        logging_config: LoggingConfig | None = None,
        plugin_policy: PluginPolicy | None = None,
        plugin_dir: str | PathLike[str] | None = None,
        discover_installed: bool = True,
        completion_provider: CompletionCallable | CompletionProvider | None = None,
        source_completion: bool = True,
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
            source_completion=source_completion,
        )
        super().__init__(
            application_id,
            executable_goal,
            display_name=display_name,
            vendor=vendor,
            product=product,
            short_product_name=short_product_name,
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
