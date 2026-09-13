from __future__ import annotations

import ipaddress
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engulf_api import BeforeGoalAPI, GoalResult, Invocation, InvocationAPI, StateScope
from engulf_clab_lab_parser import (
    TOPOLOGY_CONTEXT,
    TopologyError,
    TopologySession,
    load_topology,
    topology_path_from_args,
)
from engulf_clab_schema_api import (
    SCHEMA_CONTEXTS,
    LifecycleStage,
    PluginSchema,
    Privilege,
    SchemaBackedPlugin,
    ValueType,
    record_plugin_schema,
)
from engulf_executable_wrapper_api import (
    AfterCallEvent,
    BeforeCallEvent,
    CallContribution,
    CallMode,
    HelpAPI,
    OutcomeKind,
    PreparationFailedEvent,
    PreparedCallEvent,
)

from .allocation import (
    DEFAULT_IPV4_POOL,
    DEFAULT_IPV6_POOL,
    DEFAULT_MAX_LABS,
    Config,
    Family,
    Network,
    StickyIPError,
    TopologyRequest,
    allocation_prefix,
    allocation_units,
    assign_node_ips,
    find_available_network,
    generated_network_name,
    lab_key,
    network_subnet_of,
    parse_bool,
    parse_config,
    topology_request,
)
from .host import HostCheckError, HostInventory, inspect_host, probe_candidate
from .registry import (
    RESERVED_STATUSES,
    Allocation,
    Attempt,
    Registry,
    finish_attempt,
    read_locked,
    record_pending,
    release_all,
    release_lab,
    rollback_attempt,
)

PLUGIN_ID = "engulf_clab.sticky_ip"
_ATTEMPT_CONTEXT = "engulf_clab.sticky_ip.attempt"
_DESTROY_CONTEXT = "engulf_clab.sticky_ip.destroy"
_LEASE = "sticky-ip-registry"
_DEPLOY_COMMANDS = frozenset({"deploy", "redeploy"})
_RESERVED_NETWORKS = frozenset({"bridge", "clab", "host", "none"})

PLUGIN_SCHEMA = (
    PluginSchema(PLUGIN_ID, package="engulf_clab_sticky_ip")
    .add_runtime_var(
        "ECLAB_STICKY_IPV6",
        "Select sticky IPv6 management addresses instead of the default IPv4 family.",
        values=ValueType.BOOLEAN,
        default=False,
    )
    .add_cli_flag(
        "--eclab-sticky-ipv6",
        "Allocate fixed IPv6 management addresses instead of IPv4 addresses.",
        environment="ECLAB_STICKY_IPV6",
    )
    .add_runtime_var(
        "ECLAB_NO_STICKY_IP",
        "Disable sticky management addressing and its availability checks.",
        values=ValueType.BOOLEAN,
        default=False,
    )
    .add_cli_flag(
        "--eclab-no-sticky-ip",
        "Pass deployment through without sticky management addressing.",
        environment="ECLAB_NO_STICKY_IP",
    )
    .add_runtime_var(
        "ECLAB_STICKY_IP_MAX_LABS",
        "Limit concurrent sticky labs and size the retained allocation window.",
        values=ValueType.POSITIVE_INTEGER,
        default=DEFAULT_MAX_LABS,
    )
    .add_runtime_var(
        "ECLAB_STICKY_IPV4_POOL",
        "Replace the ordered comma-separated RFC1918 allocation pools.",
        values=ValueType.STRING,
        default=DEFAULT_IPV4_POOL,
    )
    .add_runtime_var(
        "ECLAB_STICKY_IPV6_POOL",
        "Replace the ordered comma-separated IPv6 ULA allocation pools.",
        values=ValueType.STRING,
        default=DEFAULT_IPV6_POOL,
    )
    .add_runtime_var(
        "ECLAB_STICKY_IP_EXCLUDES",
        "Exclude comma-separated private IP addresses or CIDRs from allocation.",
        values=ValueType.STRING,
    )
    .use_case("Give each lab stable fixed management addresses in a private per-lab subnet.")
    .reject("Do not combine sticky mode with Containerlab management-network CLI overrides.")
    .annotate(
        "--eclab-sticky-ipv6",
        commands=("deploy", "redeploy"),
        lifecycle=(LifecycleStage.ANALYZE_CALL, LifecycleStage.PREPARE_CALL),
    )
    .annotate(
        "--eclab-no-sticky-ip",
        commands=("deploy", "redeploy"),
        lifecycle=(LifecycleStage.ANALYZE_CALL,),
    )
    .annotate(
        "ECLAB_STICKY_IP_MAX_LABS",
        commands=("deploy", "redeploy"),
        lifecycle=(LifecycleStage.PREPARE_CALL,),
    )
    .annotate(
        "ECLAB_STICKY_IPV4_POOL",
        commands=("deploy", "redeploy"),
        lifecycle=(LifecycleStage.PREPARE_CALL,),
    )
    .annotate(
        "ECLAB_STICKY_IPV6_POOL",
        commands=("deploy", "redeploy"),
        lifecycle=(LifecycleStage.PREPARE_CALL,),
    )
    .annotate(
        "ECLAB_STICKY_IP_EXCLUDES",
        commands=("deploy", "redeploy"),
        lifecycle=(LifecycleStage.PREPARE_CALL,),
    )
    .require_host_tool(
        "docker",
        "Inspect management networks and endpoint ownership before deployment.",
        commands=("deploy", "redeploy"),
    )
    .require_host_tool(
        "ip",
        "Inspect every host route table before selecting a management subnet.",
        commands=("deploy", "redeploy"),
    )
    .require_host_tool(
        "traceroute",
        "Probe two candidate addresses with a bounded deadline before deployment.",
        commands=("deploy", "redeploy"),
    )
    .require_privilege(
        Privilege.CONTAINER_RUNTIME,
        "Availability checks require read access to Docker network and container metadata.",
        commands=("deploy", "redeploy"),
    )
    .order(
        LifecycleStage.PREPARE_CALL,
        "Sticky addresses are assigned after node-producing mutators and before materialization.",
        after=("engulf_clab.lab_parser",),
        before=("engulf_clab.lab_writer",),
    )
    .route(
        "configure-sticky-ip",
        "USAGE.md",
        "Read allocation, explicit-address, availability, and lifecycle behavior.",
    )
    .refer("USAGE.md")
)


@dataclass(frozen=True, slots=True)
class _DestroyTarget:
    all_labs: bool
    lab_key: str | None = None
    keep_network: bool = False


@dataclass(frozen=True, slots=True)
class _Plan:
    subnet: Network
    network_name: str
    node_ips: dict[str, str]
    units: int
    managed: bool
    evicted: tuple[Allocation, ...]
    cursor: tuple[int, int] | None


class StickyIPPlugin(SchemaBackedPlugin):
    plugin_id = PLUGIN_ID
    schema = PLUGIN_SCHEMA
    priority = -90
    context_reads = frozenset({TOPOLOGY_CONTEXT, _ATTEMPT_CONTEXT, _DESTROY_CONTEXT}) | SCHEMA_CONTEXTS
    context_writes = frozenset({_ATTEMPT_CONTEXT, _DESTROY_CONTEXT}) | SCHEMA_CONTEXTS

    def before_goal(
        self, invocation: Invocation, api: BeforeGoalAPI
    ) -> GoalResult[object] | None:
        del invocation
        record_plugin_schema(api, PLUGIN_SCHEMA)
        return None

    def help(self, api: HelpAPI) -> str:
        del api
        return (
            "  --eclab-sticky-ipv6  Use sticky IPv6 management addresses (IPv4 is default)\n"
            "  --eclab-no-sticky-ip  Disable sticky addressing and availability checks\n"
            "  ECLAB_STICKY_IP_MAX_LABS controls concurrency (default 64); "
            "ECLAB_STICKY_IPV4_POOL, ECLAB_STICKY_IPV6_POOL, and "
            "ECLAB_STICKY_IP_EXCLUDES configure private allocation space."
        )

    def analyze_call(
        self, event: BeforeCallEvent, api: InvocationAPI
    ) -> CallContribution | None:
        if event.mode is CallMode.HELP or not event.wrapper_args:
            return None
        command = event.wrapper_args[0]
        if command not in _DEPLOY_COMMANDS:
            return None
        try:
            disabled, _family = _mode(event.wrapper_args, event.environment)
            if disabled:
                return None
            parse_config(event.environment)
            if command == "redeploy" and _has_flag(event.wrapper_args[1:], "-a", "--all"):
                raise StickyIPError(
                    "sticky IP requires one source topology for redeploy; run each lab separately "
                    "or use --eclab-no-sticky-ip"
                )
            if (
                command == "redeploy"
                and _option_value(event.wrapper_args[1:], "--name") is not None
                and not _has_topology_option(event.wrapper_args[1:])
            ):
                raise StickyIPError(
                    "sticky IP requires one source topology for redeploy --name; add -t or "
                    "use --eclab-no-sticky-ip"
                )
            if _management_override(event.wrapper_args[1:]):
                raise StickyIPError(
                    "sticky IP cannot be combined with --network, --ipv4-subnet, or "
                    "--ipv6-subnet; put a complete setup in YAML or use --eclab-no-sticky-ip"
                )
            runtime = _option_value(event.wrapper_args[1:], "-r", "--runtime")
            if runtime is not None and runtime != "docker":
                raise StickyIPError(
                    "sticky IP currently supports the Docker runtime; use --eclab-no-sticky-ip"
                )
        except StickyIPError as error:
            api.logger.error("%s", error)
            return CallContribution(preempt_exit_code=1)
        return None

    def prepare_call(self, event: PreparedCallEvent, api: InvocationAPI) -> None:
        if not event.wrapper_args:
            return
        command = event.wrapper_args[0]
        if command == "destroy":
            self._prepare_destroy(event, api)
            return
        if command not in _DEPLOY_COMMANDS:
            return
        disabled, family = _mode(event.wrapper_args, event.environment)
        if disabled:
            return
        config = parse_config(event.environment)
        session = api.require_context(TOPOLOGY_CONTEXT)
        if not isinstance(session, TopologySession):
            raise StickyIPError("invalid shared topology session")
        document = session.materialize()
        request = topology_request(document, family)
        if not request.nodes:
            return
        workspace = api.state(StateScope.WORKSPACE).root.resolve()
        key = lab_key(workspace, request.name)
        _validate_name_override(event.wrapper_args[1:], request.name)
        destructive = command == "redeploy" or _has_flag(
            event.wrapper_args[1:], "-c", "--reconfigure"
        )
        keep_network = _has_flag(event.wrapper_args[1:], "--keep-mgmt-net")
        attempt: Attempt | None = None
        user_state = api.state(StateScope.USER)
        with api.lease(_LEASE):
            try:
                registry = read_locked(user_state)
                inventory = inspect_host()
                plan = _allocation_plan(
                    registry,
                    config,
                    request,
                    workspace,
                    key,
                    inventory,
                    destructive=destructive and not keep_network,
                )
                sequence = registry.sequence + 1
                attempt_id = uuid.uuid4().hex
                allocation = Allocation(
                    allocation_id=uuid.uuid4().hex,
                    lab_key=key,
                    workspace=str(workspace),
                    lab_name=request.name,
                    family=family,
                    network_name=plan.network_name,
                    subnet=str(plan.subnet),
                    units=plan.units,
                    node_ips=plan.node_ips,
                    status="pending",
                    sequence=sequence,
                    managed=plan.managed,
                    attempt_id=attempt_id,
                )
                attempt = record_pending(
                    user_state,
                    registry,
                    allocation,
                    evicted=plan.evicted,
                    cursor=plan.cursor,
                )
                api.set_context(_ATTEMPT_CONTEXT, attempt)
                _publish(session, api, document, request, plan)
            except BaseException:
                if attempt is not None:
                    rollback_attempt(user_state, attempt)
                raise

    def prepare_failed(self, event: PreparationFailedEvent, api: InvocationAPI) -> None:
        if not event.wrapper_args or event.wrapper_args[0] not in _DEPLOY_COMMANDS:
            return
        attempt = api.get_context(_ATTEMPT_CONTEXT)
        if isinstance(attempt, Attempt):
            with api.lease(_LEASE):
                rollback_attempt(api.state(StateScope.USER), attempt)

    def after_call(self, event: AfterCallEvent, api: InvocationAPI) -> None:
        if not event.wrapper_args:
            return
        command = event.wrapper_args[0]
        if command in _DEPLOY_COMMANDS:
            attempt = api.get_context(_ATTEMPT_CONTEXT)
            if not isinstance(attempt, Attempt):
                return
            with api.lease(_LEASE):
                if not event.outcome.process_started:
                    rollback_attempt(api.state(StateScope.USER), attempt)
                else:
                    success = (
                        event.outcome.kind is OutcomeKind.COMPLETED
                        and event.outcome.exit_code == 0
                    )
                    finish_attempt(api.state(StateScope.USER), attempt, success=success)
            return
        if (
            command != "destroy"
            or event.mode is CallMode.HELP
            or event.outcome.kind is not OutcomeKind.COMPLETED
            or event.outcome.exit_code != 0
        ):
            return
        target = api.get_context(_DESTROY_CONTEXT)
        if not isinstance(target, _DestroyTarget) or target.keep_network:
            return
        with api.lease(_LEASE):
            if target.all_labs:
                release_all(api.state(StateScope.USER))
            elif target.lab_key is not None:
                release_lab(api.state(StateScope.USER), target.lab_key)

    def _prepare_destroy(self, event: PreparedCallEvent, api: InvocationAPI) -> None:
        keep = _has_flag(event.wrapper_args[1:], "--keep-mgmt-net")
        if _has_flag(event.wrapper_args[1:], "-a", "--all"):
            api.set_context(_DESTROY_CONTEXT, _DestroyTarget(True, keep_network=keep))
            return
        try:
            path = topology_path_from_args(tuple(event.effective_args[1:]))
            document = load_topology(path, event.environment)
            name = document.get("name")
            if not isinstance(name, str) or not name:
                return
            workspace = api.state(StateScope.WORKSPACE).root.resolve()
            api.set_context(
                _DESTROY_CONTEXT,
                _DestroyTarget(False, lab_key(workspace, name), keep),
            )
        except (StickyIPError, TopologyError, OSError):
            return


def _allocation_plan(
    registry: Registry,
    config: Config,
    request: TopologyRequest,
    workspace: Path,
    key: str,
    inventory: HostInventory,
    *,
    destructive: bool,
) -> _Plan:
    if any(
        item.lab_key == key and item.status == "pending"
        for item in registry.allocations
    ):
        raise StickyIPError("another sticky IP deployment for this lab is still pending")
    active_labs = {
        item.lab_key for item in registry.allocations if item.status in RESERVED_STATUSES
    }
    if key not in active_labs and len(active_labs) >= config.max_labs:
        raise StickyIPError(
            f"sticky IP active-lab limit ({config.max_labs}) is exhausted"
        )
    network_name = request.network_name
    if network_name in _RESERVED_NETWORKS:
        raise StickyIPError(
            f"mgmt.network {network_name!r} is shared or reserved; use a private per-lab network"
        )
    network_name = network_name or generated_network_name(key)
    _validate_network_claim(registry, key, network_name)
    owned_names = {
        item.network_name
        for item in registry.allocations
        if item.lab_key == key and item.status in RESERVED_STATUSES
    }
    active_other_family = any(
        item.lab_key == key
        and item.family is not request.family
        and item.status in RESERVED_STATUSES
        for item in registry.allocations
    )
    if active_other_family and not destructive:
        raise StickyIPError(
            "changing the sticky address family of a live lab requires redeploy or deploy --reconfigure"
        )
    if request.explicit:
        assert request.explicit_subnet is not None
        if any(request.explicit_subnet.overlaps(item) for item in config.exclusions):
            raise StickyIPError(
                f"explicit subnet {request.explicit_subnet} overlaps ECLAB_STICKY_IP_EXCLUDES"
            )
        _validate_state_conflicts(registry, key, request.explicit_subnet)
        own = inventory.validate_candidate(
            request.explicit_subnet,
            network_name=network_name,
            lab_name=request.name,
            workspace=workspace,
            owned_names=owned_names,
            destructive=destructive,
        )
        if probe_candidate(request.explicit_subnet, own_addresses=own):
            raise StickyIPError(
                f"explicit subnet {request.explicit_subnet} responded to an availability probe"
            )
        evicted = tuple(
            item
            for item in registry.allocations
            if item.status == "inactive"
            and (
                item.lab_key == key
                or ipaddress.ip_network(item.subnet).overlaps(request.explicit_subnet)
            )
        )
        return _Plan(
            request.explicit_subnet,
            network_name,
            {node: str(address) for node, address in request.explicit_ips.items()},
            0,
            False,
            evicted,
            None,
        )

    units = allocation_units(len(request.nodes))
    prefix = allocation_prefix(request.family, units)
    histories = sorted(
        (
            item
            for item in registry.allocations
            if item.lab_key == key
            and item.family is request.family
            and item.managed
            and item.status != "pending"
        ),
        key=lambda item: item.sequence,
        reverse=True,
    )
    for history in histories:
        subnet = ipaddress.ip_network(history.subnet)
        if history.units < units or not _allowed_managed_subnet(subnet, config, request.family):
            continue
        if _candidate_usable(
            registry,
            inventory,
            request,
            workspace,
            key,
            subnet,
            network_name,
            owned_names,
            destructive=destructive,
        ):
            return _Plan(
                subnet,
                network_name,
                assign_node_ips(request.nodes, subnet, history.node_ips),
                history.units,
                True,
                _inactive_for_lab(registry, key),
                None,
            )
    active_history = next(
        (item for item in histories if item.status in RESERVED_STATUSES), None
    )
    if active_history is not None and active_history.units < units and not destructive:
        raise StickyIPError(
            "growing a live lab's sticky management subnet requires redeploy or deploy --reconfigure"
        )
    if active_history is not None and active_history.units < units:
        old = ipaddress.ip_network(active_history.subnet)
        expanded = old.supernet(new_prefix=prefix)
        if _allowed_managed_subnet(expanded, config, request.family) and _candidate_usable(
            registry,
            inventory,
            request,
            workspace,
            key,
            expanded,
            network_name,
            owned_names,
            destructive=destructive,
        ):
            evicted = _displaced_inactive(registry, key, expanded)
            return _Plan(
                expanded,
                network_name,
                assign_node_ips(request.nodes, expanded, active_history.node_ips),
                units,
                True,
                evicted,
                _cursor_for(config.pools(request.family), expanded),
            )

    retained = _retained_units(registry, excluding_lab=key)
    budget = config.max_labs * 2
    if retained + units <= budget:
        plan = _find_new_plan(
            registry,
            config,
            request,
            workspace,
            key,
            inventory,
            network_name,
            owned_names,
            units,
            prefix,
            destructive,
        )
        if plan is not None:
            return plan
    plan = _find_recycled_plan(
        registry,
        config,
        request,
        workspace,
        key,
        inventory,
        network_name,
        owned_names,
        units,
        prefix,
        destructive,
    )
    if plan is not None:
        return plan
    raise StickyIPError(
        "no free sticky management subnet remains; destroy an inactive lab, enlarge the "
        "private pools, or increase ECLAB_STICKY_IP_MAX_LABS"
    )


def _find_new_plan(
    registry: Registry,
    config: Config,
    request: TopologyRequest,
    workspace: Path,
    key: str,
    inventory: HostInventory,
    network_name: str,
    owned_names: set[str],
    units: int,
    prefix: int,
    destructive: bool,
) -> _Plan | None:
    pools = config.pools(request.family)
    cursor_pool, cursor_address = registry.cursors[request.family.value]
    blocked: list[Network] = [
        *config.exclusions,
        *inventory.blocked_networks(
            lab_name=request.name, workspace=workspace, owned_names=owned_names
        ),
        *(
            ipaddress.ip_network(item.subnet)
            for item in registry.allocations
            if item.lab_key != key or item.status == "inactive"
        ),
    ]
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        found = find_available_network(
            pools,
            prefix,
            blocked,
            cursor_pool=cursor_pool,
            cursor_address=cursor_address,
        )
        if found is None:
            return None
        candidate, pool_index = found
        if _candidate_usable(
            registry,
            inventory,
            request,
            workspace,
            key,
            candidate,
            network_name,
            owned_names,
            destructive=destructive,
            probe_timeout=min(0.1, max(0.01, deadline - time.monotonic())),
        ):
            return _Plan(
                candidate,
                network_name,
                assign_node_ips(request.nodes, candidate, {}),
                units,
                True,
                _inactive_for_lab(registry, key),
                (pool_index, int(candidate.network_address)),
            )
        blocked.append(candidate)
        cursor_pool, cursor_address = pool_index, int(candidate.network_address)
    raise StickyIPError("sticky IP availability probes exceeded the one-second deadline")


def _find_recycled_plan(
    registry: Registry,
    config: Config,
    request: TopologyRequest,
    workspace: Path,
    key: str,
    inventory: HostInventory,
    network_name: str,
    owned_names: set[str],
    units: int,
    prefix: int,
    destructive: bool,
) -> _Plan | None:
    cursor_address = registry.cursors[request.family.value][1]
    histories = sorted(
        {
            ipaddress.ip_network(item.subnet)
            for item in registry.allocations
            if item.family is request.family
            and item.managed
            and item.status == "inactive"
            and _allowed_managed_subnet(
                ipaddress.ip_network(item.subnet), config, request.family
            )
        },
        key=lambda item: int(item.network_address),
    )
    ordered = [item for item in histories if int(item.network_address) > cursor_address]
    ordered.extend(item for item in histories if int(item.network_address) <= cursor_address)
    deadline = time.monotonic() + 1.0
    for history in ordered:
        if time.monotonic() >= deadline:
            raise StickyIPError("sticky IP availability probes exceeded the one-second deadline")
        found = find_available_network((history,), prefix, config.exclusions)
        if found is None:
            continue
        candidate, _ = found
        if not _candidate_usable(
            registry,
            inventory,
            request,
            workspace,
            key,
            candidate,
            network_name,
            owned_names,
            destructive=destructive,
            probe_timeout=min(0.1, max(0.01, deadline - time.monotonic())),
        ):
            continue
        evicted = _displaced_inactive(registry, key, candidate)
        return _Plan(
            candidate,
            network_name,
            assign_node_ips(request.nodes, candidate, {}),
            units,
            True,
            evicted,
            _cursor_for(config.pools(request.family), candidate),
        )
    return None


def _candidate_usable(
    registry: Registry,
    inventory: HostInventory,
    request: TopologyRequest,
    workspace: Path,
    key: str,
    candidate: Network,
    network_name: str,
    owned_names: set[str],
    *,
    destructive: bool,
    probe_timeout: float = 0.1,
) -> bool:
    try:
        _validate_state_conflicts(registry, key, candidate)
        own = inventory.validate_candidate(
            candidate,
            network_name=network_name,
            lab_name=request.name,
            workspace=workspace,
            owned_names=owned_names,
            destructive=destructive,
        )
        return not probe_candidate(
            candidate, own_addresses=own, timeout=probe_timeout
        )
    except HostCheckError:
        return False


def _validate_state_conflicts(registry: Registry, key: str, candidate: Network) -> None:
    for item in registry.allocations:
        if item.lab_key == key or item.status not in RESERVED_STATUSES:
            continue
        if ipaddress.ip_network(item.subnet).overlaps(candidate):
            raise StickyIPError(
                f"candidate subnet {candidate} is reserved by active lab {item.lab_name!r}"
            )


def _validate_network_claim(registry: Registry, key: str, network_name: str) -> None:
    for item in registry.allocations:
        if (
            item.lab_key != key
            and item.network_name == network_name
            and item.status in RESERVED_STATUSES
        ):
            raise StickyIPError(
                f"management network {network_name!r} is reserved by active lab {item.lab_name!r}"
            )


def _allowed_managed_subnet(subnet: Network, config: Config, family: Family) -> bool:
    return any(network_subnet_of(subnet, pool) for pool in config.pools(family)) and not any(
        subnet.overlaps(exclusion) for exclusion in config.exclusions
    )


def _inactive_for_lab(registry: Registry, key: str) -> tuple[Allocation, ...]:
    return tuple(
        item
        for item in registry.allocations
        if item.lab_key == key and item.status == "inactive"
    )


def _displaced_inactive(
    registry: Registry, key: str, candidate: Network
) -> tuple[Allocation, ...]:
    return tuple(
        item
        for item in registry.allocations
        if item.status == "inactive"
        and (
            item.lab_key == key
            or ipaddress.ip_network(item.subnet).overlaps(candidate)
        )
    )


def _retained_units(registry: Registry, *, excluding_lab: str) -> int:
    spans = {
        (item.family.value, item.subnet): item.units
        for item in registry.allocations
        if item.lab_key != excluding_lab and item.managed
    }
    return sum(spans.values())


def _cursor_for(pools: Sequence[Network], candidate: Network) -> tuple[int, int]:
    for index, pool in enumerate(pools):
        if network_subnet_of(candidate, pool):
            return index, int(candidate.network_address)
    raise StickyIPError(f"candidate {candidate} does not belong to a configured pool")


def _publish(
    session: TopologySession,
    api: InvocationAPI,
    document: dict[str, Any],
    request: TopologyRequest,
    plan: _Plan,
) -> None:
    mutation = session.editor(PLUGIN_ID)
    _set_value(mutation, document, ("mgmt", "network"), plan.network_name)
    if plan.managed:
        _set_value(
            mutation,
            document,
            ("mgmt", request.family.subnet_field),
            str(plan.subnet),
        )
        for node, address in plan.node_ips.items():
            _set_value(
                mutation,
                document,
                ("topology", "nodes", node, request.family.node_field),
                address,
            )
    api.logger.info(
        "reserved sticky %s subnet=%s network=%s nodes=%d",
        request.family.value,
        plan.subnet,
        plan.network_name,
        len(request.nodes),
    )


def _set_value(editor: Any, document: Mapping[str, Any], path: tuple[str, ...], value: Any) -> None:
    current: Any = document
    exists = True
    for part in path:
        if not isinstance(current, Mapping) or part not in current:
            exists = False
            break
        current = current[part]
    if exists:
        if current != value:
            editor.modify(path, value)
    else:
        editor.add(path, value)


def _mode(args: Sequence[str], environment: Mapping[str, str]) -> tuple[bool, Family]:
    disabled = "--eclab-no-sticky-ip" in args or parse_bool(
        environment.get("ECLAB_NO_STICKY_IP"), name="ECLAB_NO_STICKY_IP"
    )
    ipv6 = "--eclab-sticky-ipv6" in args or parse_bool(
        environment.get("ECLAB_STICKY_IPV6"), name="ECLAB_STICKY_IPV6"
    )
    return disabled, Family.IPV6 if ipv6 else Family.IPV4


def _management_override(args: Sequence[str]) -> bool:
    return any(
        value in {"--network", "-4", "--ipv4-subnet", "-6", "--ipv6-subnet"}
        or any(
            value.startswith(f"{option}=")
            for option in ("--network", "-4", "--ipv4-subnet", "-6", "--ipv6-subnet")
        )
        for value in args
    )


def _has_topology_option(args: Sequence[str]) -> bool:
    return any(
        value in {"-t", "--topo", "--topology"}
        or any(
            value.startswith(f"{option}=")
            for option in ("-t", "--topo", "--topology")
        )
        for value in args
    )


def _has_flag(args: Sequence[str], *names: str) -> bool:
    return any(value in names for value in args)


def _option_value(args: Sequence[str], *names: str) -> str | None:
    for index, value in enumerate(args):
        if value in names:
            return args[index + 1] if index + 1 < len(args) else None
        for name in names:
            if value.startswith(f"{name}="):
                return value.removeprefix(f"{name}=")
    return None


def _validate_name_override(args: Sequence[str], topology_name: str) -> None:
    override = _option_value(args, "--name")
    if override is not None and override != topology_name:
        raise StickyIPError(
            "sticky IP requires --name to match the source topology name"
        )


plugin = StickyIPPlugin()
