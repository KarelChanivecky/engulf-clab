from __future__ import annotations

import errno
import json
import re
import socket
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engulf_api import (
    AfterGoalAPI,
    BeforeGoalAPI,
    GoalResult,
    GoalResultStatus,
    Invocation,
    InvocationAPI,
    StateScope,
)
from engulf_clab_lab_parser import TOPOLOGY_CONTEXT, TopologySession, editor
from engulf_clab_schema_api import (
    SCHEMA_CONTEXTS,
    LifecycleStage,
    PluginSchema,
    SchemaBackedPlugin,
    ValueType,
    record_plugin_schema,
)
from engulf_executable_wrapper_api import (
    BeforeCallEvent,
    CallContribution,
    CallMode,
    HelpAPI,
    PreparedCallEvent,
)

PLUGIN_ID = "engulf_clab.port_check"
_STATE_FILE = "deploy-ports.json"
_PLAN_CONTEXT = f"{PLUGIN_ID}.plan"
_FLAGS = frozenset({"--eclab-not-interactive", "--eclab-auto-port"})
_OWNER_TOKEN = re.compile(r'\("(?P<command>[^"]+)",pid=(?P<pid>\d+)')

PLUGIN_SCHEMA = (
    PluginSchema(PLUGIN_ID, package="engulf_clab_port_check")
    .add_command("deploy", "Deploy a Containerlab topology with host-port conflict handling.")
    .use_case("Resolve occupied deploy host ports with an interactive or automatic replacement.")
    .order(
        LifecycleStage.PREPARE_CALL,
        "Inspect and update selected node ports after parsing and before topology materialization.",
        after=("engulf_clab.lab_parser",),
        before=("engulf_clab.lab_writer",),
    )
    .add_cli_flag(
        "--eclab-not-interactive",
        "Fail with a port conflict diagnostic instead of prompting.",
        command="deploy",
        values=ValueType.BOOLEAN,
        default=False,
    )
    .add_cli_flag(
        "--eclab-auto-port",
        "Select an open host port automatically when a requested port is occupied.",
        command="deploy",
        values=ValueType.BOOLEAN,
        default=False,
    )
    .refer("USAGE.md")
)


@dataclass(frozen=True, slots=True)
class PortRecord:
    lab: str
    topology: str
    node: str
    port: int
    protocol: str


@dataclass(frozen=True, slots=True)
class DeployPlan:
    lab: str
    topology: str
    records: tuple[PortRecord, ...]
    remapped: tuple[tuple[str, str, int, int], ...]


class PortCheckPlugin(SchemaBackedPlugin):
    """Offer a protocol-specific replacement when a deploy port is occupied."""

    plugin_id = PLUGIN_ID
    schema = PLUGIN_SCHEMA
    priority = 110
    context_reads = SCHEMA_CONTEXTS | frozenset({TOPOLOGY_CONTEXT, _PLAN_CONTEXT})
    context_writes = SCHEMA_CONTEXTS | frozenset({_PLAN_CONTEXT})

    def before_goal(
        self, invocation: Invocation, api: BeforeGoalAPI
    ) -> GoalResult[object] | None:
        del invocation
        record_plugin_schema(api, PLUGIN_SCHEMA)
        return None

    def help(self, api: HelpAPI) -> str:
        del api
        return (
            "  --eclab-not-interactive  Fail with a port-conflict message instead of prompting\n"
            "  --eclab-auto-port        Select an open host port for each conflict"
        )

    def analyze_call(
        self, event: BeforeCallEvent, api: InvocationAPI
    ) -> CallContribution | None:
        del api
        if event.mode is CallMode.HELP or not event.wrapper_args:
            return None
        if event.wrapper_args[0] != "deploy":
            return None
        return _remove_option_indexes(event.wrapper_args)

    def prepare_call(self, event: PreparedCallEvent, api: InvocationAPI) -> None:
        if not event.wrapper_args or event.wrapper_args[0] != "deploy":
            return
        session = api.get_context(TOPOLOGY_CONTEXT)
        if not isinstance(session, TopologySession):
            return
        document = session.materialize()
        topology = document.get("topology")
        nodes = topology.get("nodes") if isinstance(topology, Mapping) else None
        if not isinstance(nodes, Mapping):
            return

        topology_path = str(session.path.resolve())
        lab = _lab_name(document, session.path)
        auto = "--eclab-auto-port" in event.wrapper_args
        noninteractive = (
            "--eclab-not-interactive" in event.wrapper_args
            or not sys.stdin.isatty()
        )
        prior_records: tuple[PortRecord, ...] | None = None
        running_labs: set[str] | None = None
        ss_inventory: dict[tuple[str, int], tuple[int | None, str]] | None = None
        selected: set[tuple[str, int]] = set()
        remapped: list[tuple[str, str, int, int]] = []
        resulting: list[PortRecord] = []

        for node_name, node in nodes.items():
            if not isinstance(node, Mapping):
                continue
            ports = node.get("ports")
            if not isinstance(ports, (list, tuple)):
                continue
            for index, declaration in enumerate(ports):
                parsed = _parse_port(declaration)
                if parsed is None:
                    continue
                host_port, container_port, protocol, suffix = parsed
                if not _port_in_use(host_port, protocol) and (protocol, host_port) not in selected:
                    selected.add((protocol, host_port))
                else:
                    if prior_records is None:
                        try:
                            prior_records = _read_records(api)
                        except (OSError, ValueError) as error:
                            api.logger.warning(
                                "could not read saved deploy port ownership: %s", error
                            )
                            prior_records = ()
                    if running_labs is None:
                        running_labs = _running_labs()
                    if ss_inventory is None:
                        ss_inventory = _socket_inventory()
                    owner = _conflict_owner(
                        host_port,
                        protocol,
                        prior_records,
                        running_labs,
                        ss_inventory,
                        lab,
                    )
                    message = _conflict_message(node_name, protocol, host_port, owner)
                    if auto:
                        replacement = _find_open_port(protocol, selected)
                    elif noninteractive:
                        api.logger.error("%s", message)
                        raise PortConflictError(message)
                    else:
                        replacement = _prompt_for_port(message, protocol, selected)
                    mutation = editor(api, PLUGIN_ID)
                    mutation.modify(
                        ("topology", "nodes", str(node_name), "ports", index),
                        f"{replacement}:{container_port}{suffix}",
                    )
                    remapped.append((str(node_name), protocol, host_port, replacement))
                    host_port = replacement
                    selected.add((protocol, host_port))
                resulting.append(
                    PortRecord(lab, topology_path, str(node_name), host_port, protocol)
                )

        api.set_context(
            _PLAN_CONTEXT,
            DeployPlan(lab, topology_path, tuple(resulting), tuple(remapped)),
            allow_unused=True,
        )

    def after_goal(
        self,
        invocation: Invocation,
        result: GoalResult[object],
        api: AfterGoalAPI,
    ) -> GoalResult[object]:
        plan = api.get_context(_PLAN_CONTEXT)
        if isinstance(plan, DeployPlan) and invocation.arguments and invocation.arguments[0] == "deploy":
            ending = "completed" if result.exit_code == 0 else f"ended with exit code {result.exit_code}"
            for node, protocol, requested, chosen in plan.remapped:
                api.logger.info(
                    "deploy used remapped host port %s/%s for node %s "
                    "(requested %s); deployment %s",
                    chosen,
                    protocol,
                    node,
                    requested,
                    ending,
                )
            if result.status is GoalResultStatus.COMPLETED and result.exit_code == 0:
                try:
                    _store_records(api, plan)
                except (OSError, ValueError) as error:
                    api.logger.warning("could not save deploy port ownership: %s", error)
        return result


class PortConflictError(RuntimeError):
    """A port conflict cannot be resolved without interactive input."""


def _remove_option_indexes(args: tuple[str, ...]) -> CallContribution | None:
    indexes: set[int] = set()
    for index, argument in enumerate(args):
        if argument == "--":
            break
        if argument in _FLAGS:
            indexes.add(index)
    return CallContribution(removals=frozenset(indexes)) if indexes else None


def _parse_port(value: Any) -> tuple[int, int, str, str] | None:
    if not isinstance(value, str):
        return None
    mapping, slash, raw_protocol = value.partition("/")
    protocol = raw_protocol.lower() if slash else "tcp"
    if protocol not in {"tcp", "udp"}:
        return None
    host, separator, container = mapping.partition(":")
    if not separator or not host.isdecimal() or not container.isdecimal():
        return None
    host_port, container_port = int(host), int(container)
    if not (1 <= host_port <= 65535 and 1 <= container_port <= 65535):
        return None
    return host_port, container_port, protocol, f"/{raw_protocol}" if slash else ""


def _port_in_use(port: int, protocol: str) -> bool:
    socket_type = socket.SOCK_STREAM if protocol == "tcp" else socket.SOCK_DGRAM
    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            with socket.socket(family, socket_type) as probe:
                if family == socket.AF_INET6:
                    probe.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                probe.bind(("0.0.0.0" if family == socket.AF_INET else "::", port))
        except OSError as error:
            if error.errno in {errno.EADDRINUSE, errno.EACCES, errno.EPERM}:
                return True
    return False


def _find_open_port(protocol: str, selected: set[tuple[str, int]]) -> int:
    socket_type = socket.SOCK_STREAM if protocol == "tcp" else socket.SOCK_DGRAM
    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            with socket.socket(family, socket_type) as probe:
                if family == socket.AF_INET6:
                    probe.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                probe.bind(("0.0.0.0" if family == socket.AF_INET else "::", 0))
                port = int(probe.getsockname()[1])
                if (protocol, port) not in selected:
                    return port
        except OSError:
            continue
    raise PortConflictError(f"could not find an open {protocol} host port")


def _prompt_for_port(message: str, protocol: str, selected: set[tuple[str, int]]) -> int:
    hint = ""
    while True:
        try:
            answer = input(
                f"{hint}{message} Would you like to use a different port? <1 - 2^16-1>: "
            )
        except EOFError as error:
            raise PortConflictError(message) from error
        if not answer.isdecimal() or not 1 <= int(answer) <= 65535:
            hint = "Enter a port from 1 through 65535. "
            continue
        port = int(answer)
        if (protocol, port) in selected or _port_in_use(port, protocol):
            hint = f"Port {port}/{protocol} is already in use; choose another. "
            continue
        return port


def _conflict_message(
    node: object,
    protocol: str,
    port: int,
    owner: str,
) -> str:
    return (
        f"Cannot deploy lab because node {node} requires {protocol} port {port} "
        f"and it is already in use by {owner}. Would you like to use a different port?"
    )


def _socket_inventory() -> dict[tuple[str, int], tuple[int | None, str]]:
    result: dict[tuple[str, int], tuple[int | None, str]] = {}
    try:
        completed = subprocess.run(
            ["ss", "-H", "-ltnup"], capture_output=True, text=True, check=False
        )
    except OSError:
        return result
    if completed.returncode:
        return result
    for line in completed.stdout.splitlines():
        fields = line.split()
        if len(fields) < 5:
            continue
        protocol = fields[0].lower()
        if protocol not in {"tcp", "udp"}:
            continue
        match = re.search(r":(\d+)$", fields[4])
        if match is None:
            continue
        owner = _OWNER_TOKEN.search(line)
        if owner:
            pid = int(owner.group("pid"))
            command = _process_commandline(pid) or owner.group("command")
            result[(protocol, int(match.group(1)))] = (pid, command)
        else:
            result[(protocol, int(match.group(1)))] = (None, "process details unavailable")
    return result


def _process_commandline(pid: int) -> str | None:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return None
    return " ".join(part.decode(errors="replace") for part in raw.split(b"\0") if part) or None


def _running_labs() -> set[str]:
    try:
        listed = subprocess.run(
            [
                "docker",
                "container",
                "ls",
                "--filter",
                "label=containerlab",
                "--quiet",
                "--no-trunc",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if listed.returncode or not listed.stdout.strip():
            return set()
        inspected = subprocess.run(
            ["docker", "container", "inspect", *listed.stdout.split()],
            capture_output=True,
            text=True,
            check=False,
        )
        payload = json.loads(inspected.stdout) if inspected.returncode == 0 else []
    except (OSError, json.JSONDecodeError):
        return set()
    labs: set[str] = set()
    if isinstance(payload, list):
        for container in payload:
            config = container.get("Config") if isinstance(container, dict) else None
            labels = config.get("Labels") if isinstance(config, dict) else None
            lab = labels.get("containerlab") if isinstance(labels, dict) else None
            if isinstance(lab, str) and lab:
                labs.add(lab)
    return labs


def _conflict_owner(
    port: int,
    protocol: str,
    records: tuple[PortRecord, ...],
    running_labs: set[str],
    inventory: Mapping[tuple[str, int], tuple[int | None, str]],
    current_lab: str,
) -> str:
    for record in records:
        if (
            record.port == port
            and record.protocol == protocol
            and record.lab in running_labs
            and record.lab != current_lab
        ):
            return f"lab {record.lab}"
    pid, command = inventory.get((protocol, port), (None, "process details unavailable"))
    return f"{pid if pid is not None else 'unknown pid'} {command}"


def _lab_name(document: Mapping[str, Any], topology_path: Any) -> str:
    topology = document.get("topology")
    name = topology.get("name") if isinstance(topology, Mapping) else None
    if isinstance(name, str) and name:
        return name
    path = str(topology_path)
    for suffix in (".clab.yml", ".clab.yaml", ".yml", ".yaml"):
        if path.endswith(suffix):
            return path.removesuffix(suffix).rsplit("/", 1)[-1]
    return path.rsplit("/", 1)[-1]


def _read_records(api: InvocationAPI) -> tuple[PortRecord, ...]:
    store = api.state(StateScope.WORKSPACE)
    if not store.exists(_STATE_FILE):
        return ()
    payload = json.loads(store.read_text(_STATE_FILE))
    records = payload.get("records", []) if isinstance(payload, dict) else []
    if not isinstance(records, list):
        return ()
    parsed: list[PortRecord] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        try:
            parsed.append(PortRecord(**item))
        except TypeError:
            continue
    return tuple(parsed)


def _store_records(api: AfterGoalAPI, plan: DeployPlan) -> None:
    store = api.state(StateScope.WORKSPACE)
    with store.transaction():
        prior = _read_records(api)
        current_topology = plan.topology
        kept = [
            record
            for record in prior
            if record.topology != current_topology and record.lab != plan.lab
        ]
        kept.extend(plan.records)
        store.write_text(
            _STATE_FILE,
            json.dumps({"version": 1, "records": [_record_dict(record) for record in kept]}),
        )


def _record_dict(record: PortRecord) -> dict[str, object]:
    return {
        "lab": record.lab,
        "topology": record.topology,
        "node": record.node,
        "port": record.port,
        "protocol": record.protocol,
    }


plugin = PortCheckPlugin()
