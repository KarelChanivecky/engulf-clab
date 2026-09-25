from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engulf_api import BeforeGoalAPI, Invocation, InvocationAPI
from engulf_clab_lab_parser import (
    TopologyError,
    derived_topology_path,
    effective_nodes,
    load_topology,
    topology_path_from_args,
)
from engulf_clab_schema_api import (
    SCHEMA_CONTEXTS,
    LifecycleStage,
    PluginSchema,
    SchemaBackedPlugin,
    record_plugin_schema,
)
from engulf_executable_wrapper_api import (
    BeforeCallEvent,
    CallContribution,
    CallMode,
    HelpAPI,
    PreparedCallEvent,
)

PLUGIN_ID = "engulf_clab.fortinet_operation_guard"
FORTINET_KINDS = frozenset({"fortinet_fortigate", "fortinet_fortiproxy"})
FORTINET_TARGET_CONTEXT = f"{PLUGIN_ID}.target"

_DEPLOY = "deploy"
_RESTART = "restart"
_RECONFIGURE_FLAGS = frozenset({"-c", "--reconfigure"})


class FortinetOperationGuardError(RuntimeError):
    """Raised when an unsupported Fortinet lifecycle operation is requested."""


class DockerInspectionError(RuntimeError):
    """Raised when the running Containerlab state cannot be inspected."""


@dataclass(frozen=True, slots=True)
class FortinetTarget:
    topology: Path
    lab_name: str | None


PLUGIN_SCHEMA = (
    PluginSchema(PLUGIN_ID, package="engulf_clab_fortinet_operation_guard")
    .use_case("Reject lifecycle operations that Fortinet Containerlab nodes do not support.")
    .reject(
        "Do not use deploy --reconfigure, restart, or deploy on an already-running "
        "lab containing a Fortinet node."
    )
    .order(
        LifecycleStage.PREPARE_CALL,
        "Inspect the selected topology before Containerlab is allowed to run.",
        after=("engulf_clab.lab_parser",),
    )
    .route(
        "fortinet-operation-limitations",
        "USAGE.md",
        "Read the unsupported Fortinet deploy and restart operations.",
    )
    .refer("USAGE.md")
)


class FortinetOperationGuardPlugin(SchemaBackedPlugin):
    """Prevent unsupported lifecycle operations for Fortinet node kinds."""

    plugin_id = PLUGIN_ID
    schema = PLUGIN_SCHEMA
    priority = 120
    context_reads = SCHEMA_CONTEXTS | frozenset({FORTINET_TARGET_CONTEXT})
    context_writes = SCHEMA_CONTEXTS | frozenset({FORTINET_TARGET_CONTEXT})

    def before_goal(self, invocation: Invocation, api: BeforeGoalAPI) -> None:
        del invocation
        record_plugin_schema(api, PLUGIN_SCHEMA)

    def help(self, api: HelpAPI) -> str:
        del api
        return (
            "  Fortinet lifecycle guard       Reject deploy --reconfigure, restart, and "
            "deploy while a Fortinet lab is running"
        )

    def analyze_call(self, event: BeforeCallEvent, api: InvocationAPI) -> CallContribution | None:
        if event.mode is CallMode.HELP or not event.wrapper_args:
            return None
        command = event.wrapper_args[0]
        if command not in {_DEPLOY, _RESTART}:
            return None

        try:
            topology = topology_path_from_args(tuple(event.wrapper_args[1:]))
            document = load_topology(topology, event.environment)
            if not any(
                node.data.get("kind") in FORTINET_KINDS for node in effective_nodes(document)
            ):
                return None
        except (OSError, TopologyError):
            # Containerlab's own parser remains authoritative for an absent or
            # malformed topology. This guard only acts when it can identify the
            # selected topology and its effective node kinds.
            return None

        operation = _explicitly_unsupported_operation(command, event.wrapper_args[1:])
        if operation is not None:
            return _preempt(api, operation)

        # A plain deploy needs a Docker read during preparation to distinguish a
        # first deploy from a deploy against running containers. Mark only this
        # invocation; no host state is changed during analysis.
        api.set_context(
            FORTINET_TARGET_CONTEXT,
            FortinetTarget(topology.resolve(), _lab_name(document, topology)),
            allow_unused=True,
        )
        return None

    def prepare_call(self, event: PreparedCallEvent, api: InvocationAPI) -> None:
        if not event.wrapper_args or event.wrapper_args[0] != _DEPLOY:
            return
        target = api.get_context(FORTINET_TARGET_CONTEXT)
        if not isinstance(target, FortinetTarget):
            return
        try:
            running = _lab_is_running(target)
        except DockerInspectionError as error:
            api.logger.error("%s", error)
            raise
        if running:
            message = (
                "Fortinet devices currently do not support deploy when the lab is already running."
            )
            api.logger.error("%s", message)
            raise FortinetOperationGuardError(message)


def _explicitly_unsupported_operation(command: str, arguments: tuple[str, ...]) -> str | None:
    if command == _RESTART:
        return "restart"
    if command == _DEPLOY and any(argument in _RECONFIGURE_FLAGS for argument in arguments):
        return "deploy --reconfigure"
    return None


def _preempt(api: InvocationAPI, operation: str) -> CallContribution:
    message = f"Fortinet devices currently do not support {operation}."
    api.logger.error("%s", message)
    return CallContribution(preempt_exit_code=1)


def _lab_name(document: dict[str, Any], topology: Path) -> str | None:
    value = document.get("name")
    if isinstance(value, str) and value:
        return value
    for suffix in (".clab.yml", ".clab.yaml", ".yml", ".yaml"):
        if topology.name.endswith(suffix):
            return topology.name[: -len(suffix)]
    return topology.stem or None


def _lab_is_running(target: FortinetTarget) -> bool:
    identifiers = _run_docker(
        ("container", "ls", "--all", "--filter", "label=containerlab", "--quiet", "--no-trunc")
    ).split()
    if not identifiers:
        return False
    try:
        payload = json.loads(_run_docker(("container", "inspect", *identifiers)))
    except json.JSONDecodeError as error:
        raise DockerInspectionError("docker container inspect returned invalid JSON") from error
    if not isinstance(payload, list):
        raise DockerInspectionError("docker container inspect returned invalid JSON")

    topology_paths = {
        target.topology.resolve(),
        derived_topology_path(target.topology).resolve(),
    }
    for item in payload:
        if not isinstance(item, dict) or not _is_running(item):
            continue
        labels = _labels(item)
        topology_label = labels.get("clab-topo-file")
        if isinstance(topology_label, str) and topology_label:
            if _resolve_label_path(topology_label, target.topology.parent) in topology_paths:
                return True
            continue
        if target.lab_name is not None and labels.get("containerlab") == target.lab_name:
            return True
    return False


def _run_docker(arguments: tuple[str, ...]) -> str:
    try:
        result = subprocess.run(
            ["docker", *arguments],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise DockerInspectionError(
            f"could not inspect running Containerlab containers: {error}"
        ) from error
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise DockerInspectionError(f"docker {' '.join(arguments[:2])} failed: {detail}")
    return result.stdout


def _is_running(item: dict[str, Any]) -> bool:
    state = item.get("State")
    return isinstance(state, dict) and state.get("Running") is True


def _labels(item: dict[str, Any]) -> dict[str, Any]:
    config = item.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    return labels if isinstance(labels, dict) else {}


def _resolve_label_path(value: str, topology_directory: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = topology_directory / path
    return path.resolve()


plugin = FortinetOperationGuardPlugin()
