"""Console entry point for the standard Containerlab application definition."""

from __future__ import annotations

import importlib.metadata
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from engulf import FRAMEWORK_ERROR_EXIT, GoalPrivilegeError, PluginPolicy
from engulf_executable_wrapper import ExecutableWrapperGoal
from engulf_executable_wrapper.completion import (
    completion_context_for_request,
    handle_internal_protocol,
)

from .app import (
    CONTAINERLAB_APPLICATION,
    ContainerlabApp,
    binary_path,
    load_completion_artifact,
    publish_completion_artifact,
)


def main() -> int:
    """Run the standard Containerlab application.

    eclab has not opted its goal into elevated startup, so Engulf refuses to
    construct the application in a privileged process. Report that refusal on
    stderr and exit with the framework error code instead of a traceback.
    """
    arguments = tuple(sys.argv[1:])
    if len(arguments) == 2 and arguments[0] == "--eclab-freeze-compatible":
        return _compatible(Path(arguments[1]))
    if os.environ.get("ENGULF_INTERNAL_PROTOCOL") == "1":
        return _internal_completion(arguments)
    try:
        with CONTAINERLAB_APPLICATION.create() as application:
            if isinstance(application.goal, ExecutableWrapperGoal):
                publish_completion_artifact(application)
            if _plugin_list_requested(arguments) and not _has_plugin_list_diagnostic(
                application
            ):
                # The diagnostic is an optional Engulf distribution.  Keep the
                # documented flag useful for a plain eclab installation rather
                # than forwarding it to Containerlab as an unknown flag.
                print(_fallback_plugin_list(application), end="")
                return 0
            return application.run()
    except GoalPrivilegeError as error:
        print(f"eclab: {error}", file=sys.stderr)
        return FRAMEWORK_ERROR_EXIT


def _internal_completion(arguments: tuple[str, ...]) -> int:
    """Answer one merged completion request with lazy plugin activation."""
    artifact = load_completion_artifact()
    if artifact is None:
        try:
            with CONTAINERLAB_APPLICATION.create() as application:
                publish_completion_artifact(application)
                return handle_internal_protocol(_wrapper_goal(application), arguments)
        except GoalPrivilegeError as error:
            print(f"eclab: {error}", file=sys.stderr)
            return FRAMEWORK_ERROR_EXIT

    compiled, _fingerprint = artifact
    static_goal = ExecutableWrapperGoal.from_compiled_completion(
        binary_path(),
        compiled,
        display_name="eclab",
        source_completion=True,
    )
    if os.environ.get("ENGULF_INTERNAL_ACTION") != "complete-context":
        return handle_internal_protocol(static_goal, arguments)
    context = completion_context_for_request(static_goal, arguments)
    owners = compiled.runtime_owners(context)
    if not owners:
        return handle_internal_protocol(static_goal, arguments)

    try:
        active_ids = frozenset(compiled.runtime_closure(owners))
        with ContainerlabApp(
            plugin_policy=PluginPolicy.allow_only(active_ids),
            source_completion=True,
        ) as application:
            return handle_internal_protocol(_wrapper_goal(application), arguments)
    except GoalPrivilegeError as error:
        print(f"eclab: {error}", file=sys.stderr)
        return FRAMEWORK_ERROR_EXIT


def _wrapper_goal(application: Any) -> ExecutableWrapperGoal:
    goal = application.goal
    if not isinstance(goal, ExecutableWrapperGoal):
        raise TypeError("eclab application goal is not an executable wrapper")
    return goal


def _compatible(requirements: Path) -> int:
    """Return success only when this executable has the frozen package versions."""
    try:
        lines = requirements.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 1
    for line in lines:
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s]+)", line.strip())
        if match is None:
            continue
        try:
            installed = importlib.metadata.version(match.group(1))
        except importlib.metadata.PackageNotFoundError:
            return 1
        if installed != match.group(2):
            return 1
    return 0


def _plugin_list_requested(arguments: tuple[str, ...]) -> bool:
    """Return whether the standalone plugin inventory was requested."""
    return arguments == ("--engulf-plugin-list",)


def _has_plugin_list_diagnostic(application: Any) -> bool:
    """Return whether Engulf discovered its isolated plugin-list extension."""
    return any(
        "--engulf-plugin-list" in getattr(extension, "triggers", ())
        for extension in application.diagnostic_extensions
    )


def _fallback_plugin_list(application: Any) -> str:
    """Render a metadata-only inventory when the optional diagnostic is absent."""
    plugins = tuple(application.active_plugins)
    post_positions = {
        plugin.plugin_id: position
        for position, plugin in enumerate(application.postprocess_plugins, 1)
    }
    rows = [
        (
            str(position),
            str(post_positions[plugin.plugin_id]),
            str(plugin.priority),
            str(plugin.elevation_requirement.value),
            str(plugin.plugin_id),
            _plugin_source(plugin.source),
        )
        for position, plugin in enumerate(plugins, 1)
    ]
    output = "Normal goal plugins\n"
    output += _plugin_table(
        ("PRE", "POST", "PRIORITY", "ELEVATION", "PLUGIN ID", "SOURCE"), rows
    )
    output += "\nDiagnostic extensions\n"
    extensions = tuple(application.diagnostic_extensions)
    diagnostic_rows = [
        (
            str(extension.diagnostic_id),
            ", ".join(extension.triggers) or "-",
            str(extension.distribution),
            str(extension.version),
            "not checked" if extension.available is None else (
                "yes" if extension.available else "no"
            ),
        )
        for extension in extensions
    ]
    output += _plugin_table(
        ("DIAGNOSTIC ID", "TRIGGERS", "DISTRIBUTION", "VERSION", "AVAILABLE"),
        diagnostic_rows,
    )
    return output


def _plugin_source(source: Any) -> str:
    kind = getattr(getattr(source, "kind", None), "value", None)
    if kind == "installed":
        distribution = source.distribution_name or "unknown-distribution"
        version = source.distribution_version or "unknown"
        return f"installed {distribution}=={version} ({source.target})"
    if kind == "directory":
        return f"directory {source.directory} ({source.target})"
    return f"direct {source.target}"


def _plugin_table(
    headers: tuple[str, ...], rows: Sequence[tuple[str, ...]]
) -> str:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    def render(row: tuple[str, ...]) -> str:
        return "  ".join(
            value.ljust(widths[index]) for index, value in enumerate(row)
        ).rstrip()

    lines = [render(headers), render(tuple("-" * width for width in widths))]
    lines.extend(render(row) for row in rows)
    if not rows:
        lines.append("(none)")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
