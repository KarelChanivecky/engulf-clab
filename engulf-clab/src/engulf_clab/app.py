"""Reusable Containerlab application for Engulf extenders."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from os import PathLike
from pathlib import Path
from typing import Any, Self, cast
from urllib.parse import unquote, urlparse

from engulf import (
    Application,
    ApplicationDefinition,
    LoggingConfig,
    LogLevelOverrides,
    PluginPolicy,
    StateHomeResolver,
    WorkspaceRootResolver,
)
from engulf_api import GoalResult, Invocation
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

from .ownership import (
    ArtifactPathResolver,
    restore_sudo_application_artifacts,
    warn_sudo_ownership_failures,
)
from .workspace import workspace_root

APPLICATION_ID = "engulf-clab"
DISPLAY_NAME = "eclab"
VENDOR = "ECLAB"
PRODUCT = "Engulf Containerlab"
SHORT_PRODUCT_NAME = "eclab"
_DEFAULT_LOGGING_CONFIG = LoggingConfig(default_level="INFO")


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


def _completion_artifact_paths(
    application_id: str,
    invocation: Invocation,
) -> tuple[Path, ...]:
    """Resolve this edition's persisted completion catalog for cleanup."""
    try:
        cache_home = invocation.environment.get("XDG_CACHE_HOME")
        if cache_home is None:
            home = invocation.environment.get("HOME")
            if not home:
                return ()
            cache_home = str(Path(home).expanduser() / ".cache")
        cache = Path(cache_home).expanduser()
        if not cache.is_absolute():
            return ()
        return (cache / application_id / "completion.json",)
    except (AttributeError, TypeError, ValueError):
        return ()


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
    editable_source_fingerprints: dict[str, str | None] = {}
    for entry in entries:
        if entry.group not in groups and not entry.group.startswith(
            "engulf.plugins.v1.dependency."
        ):
            continue
        distribution = entry.dist
        if distribution is None:
            distribution_record: dict[str, object] = {}
        else:
            distribution_name = distribution.name
            try:
                files = tuple(sorted(str(item) for item in (distribution.files or ())))
            except (OSError, TypeError, ValueError):
                files = ()
            if distribution_name not in editable_source_fingerprints:
                editable_source_fingerprints[distribution_name] = (
                    _editable_source_fingerprint(distribution)
                )
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
                "editable_source_sha256": editable_source_fingerprints[
                    distribution_name
                ],
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


def _editable_source_fingerprint(distribution: Any) -> str | None:
    """Hash editable Python sources so completion changes invalidate the cache."""
    try:
        raw_direct_url = distribution.read_text("direct_url.json")
        if raw_direct_url is None:
            return None
        direct_url = json.loads(raw_direct_url)
        if not isinstance(direct_url, Mapping):
            return None
        directory = direct_url.get("dir_info")
        if not isinstance(directory, Mapping) or directory.get("editable") is not True:
            return None
        parsed_url = urlparse(direct_url.get("url", ""))
        if parsed_url.scheme != "file" or parsed_url.netloc not in ("", "localhost"):
            return None
        project = Path(unquote(parsed_url.path))
        source = project / "src"
        if not source.is_dir():
            source = project
        ignored = {
            ".git",
            ".tox",
            ".venv",
            "__pycache__",
            "build",
            "dist",
            "node_modules",
            "test",
            "tests",
            "venv",
        }
        paths: list[Path] = []
        for directory, child_directories, filenames in os.walk(source):
            child_directories[:] = sorted(
                name for name in child_directories if name not in ignored
            )
            paths.extend(
                Path(directory) / filename
                for filename in filenames
                if filename.endswith(".py")
            )
        paths.sort()
        if not paths:
            return None
        digest = hashlib.sha256()
        for path in paths:
            digest.update(path.relative_to(source).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
        return digest.hexdigest()
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


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


class _ManagedContainerlabApplication(Application[CallOutcome]):
    """Application that restores sudo-created files when an invocation ends."""

    def configure_sudo_artifact_cleanup(
        self,
        *,
        workspace_root_resolver: WorkspaceRootResolver | None,
        state_home_resolver: StateHomeResolver | None,
        artifact_path_resolver: ArtifactPathResolver | None,
    ) -> None:
        self._sudo_workspace_root_resolver = workspace_root_resolver
        self._sudo_state_home_resolver = state_home_resolver
        self._sudo_artifact_path_resolver = artifact_path_resolver
        self._sudo_cleanup_arguments = tuple(sys.argv[1:])
        self._sudo_cleanup_done = False

    def invoke(
        self,
        argv: Sequence[str] | None = None,
        *,
        log_overrides: LogLevelOverrides | None = None,
    ) -> GoalResult[CallOutcome]:
        arguments = tuple(sys.argv[1:] if argv is None else argv)
        self._sudo_cleanup_arguments = arguments
        self._sudo_cleanup_done = False
        try:
            return super().invoke(arguments, log_overrides=log_overrides)
        finally:
            self._restore_invocation_artifacts(arguments)

    def close(self) -> None:
        try:
            super().close()
        finally:
            if not self._sudo_cleanup_done:
                self._restore_invocation_artifacts(self._sudo_cleanup_arguments)

    def _restore_invocation_artifacts(self, arguments: tuple[str, ...]) -> None:
        self._sudo_cleanup_done = True
        failures = restore_sudo_application_artifacts(
            self.application_id,
            arguments,
            workspace_root_resolver=self._sudo_workspace_root_resolver,
            state_home_resolver=self._sudo_state_home_resolver,
            artifact_path_resolver=self._sudo_artifact_path_resolver,
        )
        warn_sudo_ownership_failures(
            failures,
            application_id=self.application_id,
        )


class ContainerlabApp(_ManagedContainerlabApplication):
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
            logging_config=(
                _DEFAULT_LOGGING_CONFIG if logging_config is None else logging_config
            ),
            plugin_policy=(
                PluginPolicy.declared() if plugin_policy is None else plugin_policy
            ),
            plugin_dir=plugin_dir,
            discover_installed=discover_installed,
            workspace_root_resolver=workspace_root_resolver,
            state_home_resolver=state_home_resolver,
        )
        self.configure_sudo_artifact_cleanup(
            workspace_root_resolver=workspace_root_resolver,
            state_home_resolver=state_home_resolver,
            artifact_path_resolver=_completion_artifact_paths,
        )

    @property
    def binary(self) -> str:
        """Return the executable selected for this Containerlab application."""
        goal = self.goal
        assert isinstance(goal, ExecutableWrapperGoal)
        return goal.executable


@dataclass(frozen=True, slots=True, kw_only=True)
class ContainerlabApplicationDefinition(ApplicationDefinition[CallOutcome]):
    """Edition definition whose applications restore sudo-owned artifacts."""

    artifact_path_resolver: ArtifactPathResolver | None = _completion_artifact_paths

    def __post_init__(self) -> None:
        ApplicationDefinition.__post_init__(self)
        if self.artifact_path_resolver is not None and not callable(
            self.artifact_path_resolver
        ):
            raise TypeError("artifact_path_resolver must be callable or None")

    def edition(
        self,
        *,
        display_name: str,
        vendor: str | None = None,
        product: str | None = None,
        short_product_name: str | None = None,
        version: str | None = None,
        include_plugins: Iterable[str] = (),
        require_plugins: Iterable[str] = (),
    ) -> Self:
        """Return an edition definition that retains the managed application factory."""
        return cast(
            Self,
            ApplicationDefinition.edition(
                self,
                display_name=display_name,
                vendor=vendor,
                product=product,
                short_product_name=short_product_name,
                version=version,
                include_plugins=include_plugins,
                require_plugins=require_plugins,
            ),
        )

    def with_artifact_path_resolver(
        self,
        resolver: ArtifactPathResolver | None,
    ) -> Self:
        """Return this definition with additional edition-owned artifact roots."""
        if resolver is not None and not callable(resolver):
            raise TypeError("artifact_path_resolver must be callable or None")
        if resolver is None:
            return replace(self, artifact_path_resolver=None)

        current = self.artifact_path_resolver

        def combined(
            application_id: str,
            invocation: Invocation,
        ) -> tuple[str | os.PathLike[str], ...]:
            existing = () if current is None else tuple(current(application_id, invocation))
            return (*existing, *tuple(resolver(application_id, invocation)))

        return replace(self, artifact_path_resolver=combined)

    def create(
        self,
        *,
        plugin_dir: str | os.PathLike[str] | None = None,
        discover_installed: bool = True,
    ) -> Application[CallOutcome]:
        """Create a managed application while preserving the definition contract."""
        application = _ManagedContainerlabApplication(
            self.application_id,
            self.goal_factory(),
            display_name=self.display_name,
            vendor=self.vendor,
            product=self.product,
            short_product_name=self.short_product_name,
            version=self.version,
            plugin_policy=self.plugin_policy,
            required_plugin_ids=self.required_plugin_ids,
            plugin_declaration_application_ids=(
                self.plugin_declaration_application_ids
            ),
            logging_config=self.logging_config,
            plugin_dir=plugin_dir,
            discover_installed=discover_installed,
            workspace_root_resolver=self.workspace_root_resolver,
            state_home_resolver=self.state_home_resolver,
            diagnostic_isolation_config=self.diagnostic_isolation_config,
        )
        application.configure_sudo_artifact_cleanup(
            workspace_root_resolver=self.workspace_root_resolver,
            state_home_resolver=self.state_home_resolver,
            artifact_path_resolver=self.artifact_path_resolver,
        )
        return application


# This definition is deliberately import-safe: editions can derive their own
# identity and plugin set without constructing an application or discovering
# plugins. Its overridden ``create()`` gives every derived edition the shared
# sudo-artifact lifecycle automatically.
CONTAINERLAB_APPLICATION = ContainerlabApplicationDefinition(
    application_id=APPLICATION_ID,
    display_name=DISPLAY_NAME,
    goal_factory=_containerlab_goal,
    vendor=VENDOR,
    product=PRODUCT,
    short_product_name=SHORT_PRODUCT_NAME,
    version=VERSION,
    logging_config=_DEFAULT_LOGGING_CONFIG,
    plugin_policy=PluginPolicy.declared(),
    workspace_root_resolver=workspace_root,
)
