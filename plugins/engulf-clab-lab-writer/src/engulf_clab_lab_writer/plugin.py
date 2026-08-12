from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import yaml
from engulf_api import DependencyPosition, InvocationAPI, PluginDependency
from engulf_clab_lab_parser import (
    TOPOLOGY_CONTEXT,
    TopologySession,
    topology_path_from_args,
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

_PREFIX = ".engulf-clab-lab-"


class TopologyCollectorPlugin(ExecutableWrapperPlugin):
    plugin_id = "engulf_clab.lab_writer"
    priority = -100
    plugin_dependencies = (
        PluginDependency(
            "engulf_clab.lab_parser",
            preprocess=DependencyPosition.BEFORE,
            postprocess=None,
        ),
    )
    context_reads = frozenset({TOPOLOGY_CONTEXT})

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
            raise RuntimeError("invalid topology session")
        target = _generated_path(event.effective_args)
        if target is None:
            raise RuntimeError("generated topology argument is missing")
        descriptor, staged_name = tempfile.mkstemp(
            prefix=f"{target.name}.", dir=target.parent, text=True
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                yaml.safe_dump(session.materialize(), handle, sort_keys=False)
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
        elif any(value.startswith(prefix) for prefix in ("-t=", "--topo=", "--topology=")):
            indexes.add(index)
    return {index for index in indexes if index < len(args)}


def _generated_path(args: tuple[str, ...]) -> Path | None:
    for value in args:
        path = Path(value)
        if path.name.startswith(_PREFIX):
            return path
    return None
