from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from engulf_api import (
    BeforeGoalAPI,
    DependencyPosition,
    GoalResult,
    Invocation,
    InvocationAPI,
    PluginDependency,
)
from engulf_clab_lab_parser import (
    TOPOLOGY_CONTEXT,
    WRITER_TEMP_PREFIX,
    TopologySession,
    topology_path_from_args,
)
from engulf_clab_schema_api import (
    SCHEMA_CONTEXTS,
    SCHEMA_PLUGIN_DEPENDENCY,
    LifecycleStage,
    PluginSchema,
    record_plugin_schema,
)
from engulf_executable_wrapper_api import (
    AdditionPlacement,
    AfterCallEvent,
    ArgumentAddition,
    BeforeCallEvent,
    CallContribution,
    CallMode,
    ExecutableWrapperPlugin,
    PreparedCallEvent,
)

_PREFIX = WRITER_TEMP_PREFIX
PLUGIN_SCHEMA = (
    PluginSchema("engulf_clab.lab_writer", package="engulf_clab_lab_writer")
    .use_case(
        "Materialize all plugin topology edits into a temporary topology for Containerlab."
    )
    .reject("Do not edit or persist the generated temporary topology.")
    .order(
        LifecycleStage.PREPARE_CALL,
        "The writer runs after the parser and topology mutators so it serializes their final result.",
        after=("engulf_clab.lab_parser",),
    )
    .route(
        "materialize-topology",
        "USAGE.md",
        "Read temporary topology ownership, forwarding, and cleanup behavior.",
    )
    .refer("USAGE.md")
)


class TopologyCollectorPlugin(ExecutableWrapperPlugin):
    plugin_id = "engulf_clab.lab_writer"
    priority = -100
    plugin_dependencies = (
        PluginDependency(
            "engulf_clab.lab_parser",
            preprocess=DependencyPosition.BEFORE,
            postprocess=None,
        ),
        SCHEMA_PLUGIN_DEPENDENCY,
    )
    context_reads = frozenset({TOPOLOGY_CONTEXT}) | SCHEMA_CONTEXTS
    context_writes = SCHEMA_CONTEXTS

    def before_goal(
        self, invocation: Invocation, api: BeforeGoalAPI
    ) -> GoalResult[object] | None:
        del invocation
        record_plugin_schema(api, PLUGIN_SCHEMA)
        return None

    def analyze_call(
        self, event: BeforeCallEvent, api: InvocationAPI
    ) -> CallContribution | None:
        if (
            event.mode is CallMode.HELP
            or not event.wrapper_args
            or event.wrapper_args[0] != "deploy"
        ):
            return None
        removals = _topology_indexes(event.wrapper_args)
        source = topology_path_from_args(tuple(event.wrapper_args[1:]))
        target = source.parent / f"{_PREFIX}{uuid.uuid4().hex}.clab.yml"
        return CallContribution(
            removals=frozenset(removals),
            additions=(
                ArgumentAddition(
                    ("-t", str(target)), AdditionPlacement.BEFORE_SEPARATOR
                ),
            ),
        )

    def prepare_call(self, event: PreparedCallEvent, api: InvocationAPI) -> None:
        if not event.wrapper_args or event.wrapper_args[0] != "deploy":
            return
        session = api.require_context(TOPOLOGY_CONTEXT)
        if not isinstance(session, TopologySession):
            raise TypeError("invalid topology session")
        target = _generated_path(event.effective_args)
        if target is None:
            raise RuntimeError("generated topology argument is missing")
        _sweep_stale_topologies(target.parent)
        descriptor, staged_name = tempfile.mkstemp(
            prefix=f"{target.name}.", dir=target.parent, text=True
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                yaml.safe_dump(
                    _escape_rendered_dollars(session.materialize()),
                    handle,
                    sort_keys=False,
                )
            Path(staged_name).replace(target)
        except BaseException:
            Path(staged_name).unlink(missing_ok=True)
            raise

    def after_call(self, event: AfterCallEvent, api: InvocationAPI) -> None:
        target = _generated_path(event.effective_args)
        if target is not None:
            target.unlink(missing_ok=True)


def _topology_indexes(args: tuple[str, ...]) -> set[int]:
    indexes: set[int] = set()
    for index, value in enumerate(args):
        if value in {"-t", "--topo", "--topology"}:
            indexes.update((index, index + 1))
        elif any(
            value.startswith(prefix) for prefix in ("-t=", "--topo=", "--topology=")
        ):
            indexes.add(index)
    return {index for index in indexes if index < len(args)}


def _generated_path(args: tuple[str, ...]) -> Path | None:
    for value in args:
        path = Path(value)
        if path.name.startswith(_PREFIX):
            return path
    return None


def _sweep_stale_topologies(directory: Path) -> None:
    """Remove leftover writer temp topology files before a fresh deploy.

    A prior deploy that was killed before ``after_call`` could run leaves a
    ``.engulf-clab-lab-*.clab.yml`` beside the source topology. On the next
    deploy these stale files are neither the active input (the writer
    generates a fresh path) nor needed for cleanup, so they are unlinked here
    to keep the directory tidy and the parser's glob unambiguous. A file
    matching the prefix that is actively in use (the staged path about to be
    written) is skipped defensively, though that should not occur because
    ``prepare_call`` runs before the staged file exists.
    """
    if not directory.is_dir():
        return
    for stale in directory.glob(f"{_PREFIX}*.clab.yml"):
        stale.unlink(missing_ok=True)


def _escape_rendered_dollars(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("$", "$$")
    if isinstance(value, dict):
        return {
            _escape_rendered_dollars(key): _escape_rendered_dollars(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_escape_rendered_dollars(item) for item in value]
    return value
