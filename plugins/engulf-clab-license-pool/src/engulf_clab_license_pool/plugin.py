from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from engulf_api import (
    ApplicationMetadata,
    BeforeGoalAPI,
    GoalResult,
    Invocation,
    InvocationAPI,
    StateScope,
)
from engulf_clab_lab_parser import (
    TOPOLOGY_CONTEXT,
    TopologyError,
    TopologySession,
    editor,
    effective_nodes,
    is_topology_mutation_command,
)
from engulf_clab_schema_api import (
    SCHEMA_CONTEXTS,
    ExplainedValue,
    LifecycleStage,
    PathBase,
    PluginSchema,
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

_FILE = "license-pools.json"
_STATE_VERSION = 2
_INVOCATION_ALLOCATION_CONTEXT = "engulf_clab.license_pool.invocation_allocation"

# Published for plugins outside this package -- typically an edition-specific
# one that must reason about the license a node actually received, such as
# recognizing a file suffix this plugin has no opinion about. It is the only
# supported way to learn that: allocation state is plugin-private, and the
# topology by this point holds the copied path rather than the pool origin.
LICENSE_SELECTION_CONTEXT = "engulf_clab.license_pool.selection"
_NON_ALPHANUMERIC = re.compile(r"[^A-Z0-9]+")
_LEGACY_STATE_DIRECTORY = ".engulf-clab"
# Allocation identity rides on the node environment rather than a top-level
# `uuid:` field. Containerlab's own schema has no `uuid` node property, so a
# topology carrying one is rejected by every subcommand that validates the raw
# document (graph, inspect, destroy) even though deploy accepted it. `env` is a
# field Containerlab already defines, so identity survives schema validation
# everywhere. The name is deliberately not edition-prefixed: it is the same
# variable the guest uses for its own UUID, so the license and the VM it is
# bound to cannot disagree.
UUID_ENVIRONMENT = "FOS_UUID"

# Fixed across every edition, matching engulf-clab-wan's LABEL_PREFIX
# convention: topology labels/env vars must stay portable regardless of the
# active application's product metadata. Unlike labels, the topology-local
# state directory below is deliberately still derived from application
# metadata, so every edition's state converges on the same directory as long
# as they share the same short_product_name.
LABEL_PREFIX = "ECLAB"
LICENSE_POOL_STRATEGY_ENVIRONMENT = f"{LABEL_PREFIX}_LICENSE_POOL_STRATEGY"


class LicenseStrategy(StrEnum):
    STICKY = "sticky"
    ROUND_ROBIN = "round-robin"
    LEAST_RECENTLY_USED = "least-recently-used"


_STRATEGY_VALUES = (
    ExplainedValue(
        LicenseStrategy.STICKY.value,
        "Retain active claims and preserve the existing claim-history preference.",
    ),
    ExplainedValue(
        LicenseStrategy.ROUND_ROBIN.value,
        "Choose the next available entry by index from the sorted pool.",
    ),
    ExplainedValue(
        LicenseStrategy.LEAST_RECENTLY_USED.value,
        "Choose the available entry with the oldest recorded use.",
    ),
)


class LicensePoolError(RuntimeError):
    pass


PLUGIN_SCHEMA = (
    PluginSchema("engulf_clab.license_pool", package="engulf_clab_license_pool")
    .add_node_prop(
        "license",
        "Select a license pool with $NAME or a directory path, or request a frozen-lab license prompt.",
        values=ValueType.STRING,
    )
    .add_node_var(
        UUID_ENVIRONMENT,
        "Set a stable node identity for repeatable license allocation.",
        values=ValueType.UUID,
    )
    .add_node_var(
        "ECLAB_LIC_CLAMP",
        "Require a specific available license filename or path from the selected pool.",
        values=ValueType.FILE_PATH,
    )
    .add_runtime_var(
        LICENSE_POOL_STRATEGY_ENVIRONMENT,
        "Set the persistent license-pool selection strategy; the matching CLI flag takes precedence.",
        values=_STRATEGY_VALUES,
        default=LicenseStrategy.LEAST_RECENTLY_USED.value,
    )
    .add_cli_flag(
        "--eclab-license-pool-strategy",
        "Select the license-pool allocation strategy for this invocation.",
        values=_STRATEGY_VALUES,
        default=LicenseStrategy.LEAST_RECENTLY_USED.value,
        environment=LICENSE_POOL_STRATEGY_ENVIRONMENT,
    )
    .add_runtime_var(
        "ECLAB_LICENSE",
        "Set the default frozen-lab license source; the matching CLI flag takes precedence.",
        values=(ValueType.FILE_PATH, ValueType.DIRECTORY_PATH, ValueType.STRING),
    )
    .add_cli_flag(
        "--eclab-license",
        "Provide the default non-interactive frozen-lab license source.",
        values=(ValueType.FILE_PATH, ValueType.DIRECTORY_PATH, ValueType.STRING),
        environment="ECLAB_LICENSE",
    )
    .add_runtime_var(
        "ECLAB_LICENSE_*",
        "Provide a node-specific frozen-lab license source.",
        values=(ValueType.FILE_PATH, ValueType.DIRECTORY_PATH, ValueType.STRING),
    )
    .annotate(
        "license",
        commands=("deploy", "destroy"),
        lifecycle=(LifecycleStage.PREPARE_CALL, LifecycleStage.AFTER_CALL),
        requires=(
            "$POOL names an invocation environment variable containing a pool directory",
            "any other value naming a directory is itself the pool",
        ),
        implies=(
            "a successful deploy copies the selected license into lab-local state",
            "an unsuccessful deploy rolls back claims and copies created by that invocation",
        ),
        examples=(
            "$ROUTER_LICENSE_POOL",
            "/srv/licenses/router",
            "__ECLAB_LICENSE_PROMPT__",
        ),
    )
    .annotate(
        UUID_ENVIRONMENT,
        commands=("deploy", "redeploy"),
        implies=("stable allocation identity across node renames",),
    )
    .annotate(
        "ECLAB_LIC_CLAMP",
        commands=("deploy", "redeploy"),
        requires=("license selects a $POOL",),
        path_base=PathBase.LICENSE_POOL,
    )
    .annotate(
        "--eclab-license-pool-strategy",
        commands=("deploy", "redeploy"),
        lifecycle=(LifecycleStage.PREPARE_CALL,),
        implies=("active claims remain stable for deployment retries",),
    )
    .annotate(
        LICENSE_POOL_STRATEGY_ENVIRONMENT,
        commands=("deploy", "redeploy"),
        lifecycle=(LifecycleStage.PREPARE_CALL,),
        implies=("used when --eclab-license-pool-strategy is absent",),
    )
    .annotate(
        "ECLAB_LICENSE",
        commands=("deploy", "redeploy"),
        requires=("license is __ECLAB_LICENSE_PROMPT__",),
        path_base=PathBase.INVOCATION_DIRECTORY,
    )
    .annotate(
        "--eclab-license",
        commands=("deploy", "redeploy"),
        requires=("license is __ECLAB_LICENSE_PROMPT__",),
        path_base=PathBase.INVOCATION_DIRECTORY,
    )
    .annotate(
        "ECLAB_LICENSE_*",
        commands=("deploy", "redeploy"),
        requires=("license is __ECLAB_LICENSE_PROMPT__",),
        implies=("override ECLAB_LICENSE for the named node",),
        path_base=PathBase.INVOCATION_DIRECTORY,
    )
    .use_case(
        "Lease one license file per node from a shared directory without embedding license contents."
    )
    .reject("Do not commit license files, pool paths, or generated lab-local copies.")
    .order(
        LifecycleStage.PREPARE_CALL,
        "License allocation mutates the parsed topology before final serialization.",
        after=("engulf_clab.lab_parser",),
        before=("engulf_clab.lab_writer",),
    )
    .route(
        "assign-node-license",
        "USAGE.md",
        "Read pool selection, stable identity, prompts, leases, and cleanup.",
    )
    .refer("USAGE.md")
)


@dataclass(frozen=True, slots=True)
class LicenseContract:
    state_prefix: str

    @property
    def clamp_environment(self) -> str:
        return f"{LABEL_PREFIX}_LIC_CLAMP"

    @property
    def prompt_marker(self) -> str:
        return f"__{LABEL_PREFIX}_LICENSE_PROMPT__"

    @property
    def license_environment(self) -> str:
        return f"{LABEL_PREFIX}_LICENSE"

    @property
    def state_directory(self) -> str:
        return f".{self.state_prefix.lower()}"

    def node_license_environment(self, node_name: str) -> str:
        node = "".join(
            character if character.isalnum() else "_" for character in node_name.upper()
        )
        return f"{self.license_environment}_{node}"


@dataclass(frozen=True, slots=True)
class _InvocationAllocation:
    claims: tuple[tuple[str, str, str], ...] = ()
    copies: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LicenseSelection:
    """One node's resolved license, as published on LICENSE_SELECTION_CONTEXT.

    `pool` is the directory a pooled license was allocated from, and is None
    when the license was named directly. Reading plugins should branch on
    `from_pool` rather than on the path, which is absolute and host-specific.
    """

    node: str
    source_name: str
    source_path: str
    pool: str | None = None

    @property
    def from_pool(self) -> bool:
        return self.pool is not None


def _log_selection(api: InvocationAPI, selection: object) -> None:
    if not isinstance(selection, Mapping):
        return
    for node, value in sorted(selection.items()):
        if isinstance(value, LicenseSelection):
            # Basename and a flag only: as with the selection log in
            # prepare_call, pool and source paths stay out of the record.
            api.logger.debug(
                "license provenance node=%r basename=%r from_pool=%r",
                node,
                value.source_name,
                value.from_pool,
            )


def license_contract(application: ApplicationMetadata) -> LicenseContract:
    short_name = getattr(application, "short_product_name", None)
    product = getattr(application, "product", None)
    name = short_name if isinstance(short_name, str) and short_name.strip() else product
    if not isinstance(name, str) or not name.strip():
        raise LicensePoolError("application product metadata must be a nonempty string")
    prefix = _NON_ALPHANUMERIC.sub("_", name.upper()).strip("_")
    if not prefix:
        raise LicensePoolError(f"cannot derive environment prefix from {name!r}")
    return LicenseContract(prefix)


class LicensePoolPlugin(SchemaBackedPlugin):
    plugin_id = "engulf_clab.license_pool"
    schema = PLUGIN_SCHEMA
    priority = 60
    context_reads = (
        frozenset(
            {
                TOPOLOGY_CONTEXT,
                _INVOCATION_ALLOCATION_CONTEXT,
                LICENSE_SELECTION_CONTEXT,
            }
        )
        | SCHEMA_CONTEXTS
    )
    context_writes = (
        frozenset({_INVOCATION_ALLOCATION_CONTEXT, LICENSE_SELECTION_CONTEXT})
        | SCHEMA_CONTEXTS
    )

    def before_goal(
        self, invocation: Invocation, api: BeforeGoalAPI
    ) -> GoalResult[object] | None:
        del invocation
        record_plugin_schema(api, PLUGIN_SCHEMA)
        return None

    def help(self, api: HelpAPI) -> str:
        api.logger.debug("rendering license-pool help")
        contract = license_contract(api.application)
        return (
            "  Node YAML fields:\n"
            "    license: $POOL              Allocate from invocation environment POOL directory\n"
            "    license: <directory>        Allocate from that pool directory directly\n"
            f"    env.{UUID_ENVIRONMENT}: <uuid>     Recommended stable allocation identity\n"
            f"    env.{contract.clamp_environment}: file   Require this available pool filename/path\n"
            f"    license: {contract.prompt_marker}  Prompt for a file, pool, or $VARIABLE in frozen labs\n"
            "  --eclab-license-pool-strategy STRATEGY\n"
            "      least-recently-used (default), sticky, or round-robin\n"
            f"  {LICENSE_POOL_STRATEGY_ENVIRONMENT} is the persistent strategy default; CLI wins.\n"
            "  --eclab-license VALUE        Default non-interactive frozen-lab license\n"
            f"  {contract.license_environment} is the persistent environment default; "
            "--eclab-license wins.\n"
            f"  {contract.license_environment}_<NODE> remains the per-node prompt override.\n"
            "  Pools contain top-level regular files and are leased across workspaces.\n"
            "  Deploy and redeploy log each selected license basename with its node; source paths stay private.\n"
            "  Failed deployment rolls back new claims; successful destroy releases workspace claims."
        )

    def analyze_call(
        self, event: BeforeCallEvent, api: InvocationAPI
    ) -> CallContribution | None:
        return None

    def prepare_call(self, event: PreparedCallEvent, api: InvocationAPI) -> None:
        if not is_topology_mutation_command(event.wrapper_args):
            return
        session = api.require_context(TOPOLOGY_CONTEXT)
        if not isinstance(session, TopologySession):
            raise LicensePoolError("invalid shared topology session")
        topology = session.original_document()
        _warn_legacy_uuid(api, topology)
        workspace = api.state(StateScope.WORKSPACE).root
        contract = license_contract(api.application)
        strategy = _license_strategy(event.environment)
        requests = _requests(topology, event.environment, workspace, contract)
        prompt_requests, direct = _prompt_requests(
            topology, event.environment, workspace, contract
        )
        requests.extend(prompt_requests)
        if not requests and not direct:
            return
        with api.leases(
            tuple(sorted({_lease(pool) for _node, pool, _clamp, _claim in requests}))
        ):
            state = api.state(StateScope.USER)
            assigned, created_claims = _claim_with_created(state, requests, strategy)
        allocation = _InvocationAllocation(claims=created_claims)
        try:
            api.set_context(_INVOCATION_ALLOCATION_CONTEXT, allocation)
            assigned.update({claim: source for claim, source in direct.values()})
            mutation = editor(api, self.plugin_id)
            selections = [(node, claim) for node, _pool, _clamp, claim in requests]
            selections.extend(
                (node, claim) for node, (claim, _source) in direct.items()
            )
            # Only `requests` carry a pool; `direct` entries name a file. Prompt
            # answers that resolved to a pool were folded into `requests` above,
            # so they are correctly reported as pooled.
            pools = {node: pool for node, pool, _clamp, _claim in requests}
            published: dict[str, LicenseSelection] = {}
            for node, claim in selections:
                source = Path(assigned[claim])
                published[node] = LicenseSelection(
                    node=node,
                    source_name=source.name,
                    source_path=str(source),
                    pool=pools.get(node),
                )
                target = _copy_path(session.path.parent, claim, source.name, contract)
                if not target.exists():
                    allocation = _InvocationAllocation(
                        claims=allocation.claims,
                        copies=(*allocation.copies, str(target)),
                    )
                    api.set_context(_INVOCATION_ALLOCATION_CONTEXT, allocation)
                copied = _copy_to_lab(source, session.path.parent, claim, contract)
                api.logger.info(
                    "selected license basename=%r for node=%r",
                    source.name,
                    node,
                )
                mutation.modify(("topology", "nodes", node, "license"), str(copied))
            api.set_context(LICENSE_SELECTION_CONTEXT, MappingProxyType(published))
            # Read back at the point of publication, and log provenance from
            # what the context actually holds. Reading marks the context
            # consumed, so an edition that ships no reader for this extension
            # point does not trip the framework's unread-context warning.
            _log_selection(api, api.get_context(LICENSE_SELECTION_CONTEXT))
        except BaseException:
            # Engulf never sends prepare_failed to the plugin that raised, so this
            # attempt's claims and copies are released here. BaseException rather
            # than Exception: an interrupt is not an Exception and would otherwise
            # strand a claimed license on Ctrl-C.
            self._rollback_deploy(api, allocation)
            raise

    def prepare_failed(self, event: PreparationFailedEvent, api: InvocationAPI) -> None:
        if not is_topology_mutation_command(event.wrapper_args):
            return
        allocation = api.get_context(_INVOCATION_ALLOCATION_CONTEXT)
        if isinstance(allocation, _InvocationAllocation):
            self._rollback_deploy(api, allocation)

    def after_call(self, event: AfterCallEvent, api: InvocationAPI) -> None:
        allocation = api.get_context(_INVOCATION_ALLOCATION_CONTEXT)
        if is_topology_mutation_command(event.wrapper_args):
            if isinstance(allocation, _InvocationAllocation) and (
                event.outcome.kind is not OutcomeKind.COMPLETED
                or event.outcome.exit_code != 0
            ):
                self._rollback_deploy(api, allocation)
            return
        if (
            not event.wrapper_args
            or event.wrapper_args[0] != "destroy"
            or event.mode is CallMode.HELP
        ):
            return
        if event.outcome.kind is not OutcomeKind.COMPLETED or event.outcome.exit_code:
            return
        with api.lease("license-pool-registry"):
            state = api.state(StateScope.USER)
            contract = license_contract(api.application)
            if any(value in {"-a", "--all"} for value in event.wrapper_args[1:]):
                # Read the claimed workspaces before releasing them: afterwards the
                # registry no longer records which labs hold copied licenses, and
                # releasing the registry alone would leave every copy on disk.
                roots = _claimed_workspaces(state)
                _release_all(state)
                for root in roots:
                    _remove_license_copies(Path(root), contract)
                return
            workspace = api.state(StateScope.WORKSPACE)
            _release_workspace(state, str(workspace.root))
            _remove_license_copies(workspace.root, contract)

    def _rollback_deploy(
        self, api: InvocationAPI, allocation: _InvocationAllocation
    ) -> None:
        pools = tuple(sorted({pool for pool, _path, _claim in allocation.claims}))
        with api.leases(tuple(_lease(pool) for pool in pools)):
            _release_claims(api.state(StateScope.USER), allocation.claims)
        for value in allocation.copies:
            target = Path(value)
            target.unlink(missing_ok=True)
            _remove_empty_copy_parents(target.parent)


def _pool(
    value: str, environ: Mapping[str, str], contract: LicenseContract
) -> Path | None:
    """Resolve one node `license:` value to a pool directory, or None.

    The lab parser expands Containerlab environment expressions before any
    plugin reads the topology, so `license: $POOL` normally arrives here
    already rendered as the pool directory itself. A pool is therefore
    recognised by the value naming a directory, not by a leading `$`. A bare
    `$NAME` still survives expansion when the variable is unset, and that case
    keeps naming the variable in the error rather than reporting a missing
    file. Anything else -- a regular file, the frozen prompt marker, a path
    that does not exist -- is not this plugin's to allocate and is left for
    Containerlab or `_prompt_requests` to handle.
    """
    if value == contract.prompt_marker:
        return None
    if value.startswith("$"):
        pool_name = value[1:].strip("{}")
        if not pool_name or pool_name not in environ:
            raise LicensePoolError(f"license pool ${pool_name} is not set")
        pool = Path(environ[pool_name]).expanduser().resolve()
        if not pool.is_dir():
            raise LicensePoolError(
                f"license pool ${pool_name} is not a directory: {pool}"
            )
        return pool
    candidate = Path(value).expanduser().resolve()
    return candidate if candidate.is_dir() else None


def _requests(
    data: dict[str, Any],
    environ: Mapping[str, str],
    workspace: Path,
    contract: LicenseContract,
) -> list[tuple[str, str, str | None, str]]:
    nodes = data.get("topology", {}).get("nodes", {})
    if not isinstance(nodes, dict):
        raise LicensePoolError("topology.nodes is required")
    try:
        resolved_nodes = effective_nodes(data)
    except TopologyError as error:
        raise LicensePoolError(str(error)) from error
    result = []
    for node in resolved_nodes:
        license_value = node.data.get("license")
        if not isinstance(license_value, str):
            continue
        pool = _pool(license_value, environ, contract)
        if pool is None:
            continue
        env = node.data.get("env", {})
        if env is None:
            env = {}
        if not isinstance(env, Mapping):
            raise LicensePoolError(f"node {node.name} env must be a YAML mapping")
        clamp = env.get(contract.clamp_environment)
        if clamp is not None and not isinstance(clamp, str):
            raise LicensePoolError(
                f"node {node.name} {contract.clamp_environment} must be a string"
            )
        identity = env.get(UUID_ENVIRONMENT, node.name)
        if not isinstance(identity, str) or not identity:
            raise LicensePoolError(
                f"node {node.name} {UUID_ENVIRONMENT} must be a nonempty string"
            )
        result.append((node.name, str(pool), clamp, f"{workspace}:{identity}"))
    return result


def _prompt_requests(
    data: dict[str, Any],
    environ: Mapping[str, str],
    workspace: Path,
    contract: LicenseContract,
) -> tuple[list[tuple[str, str, str | None, str]], dict[str, tuple[str, str]]]:
    nodes = data.get("topology", {}).get("nodes", {})
    if not isinstance(nodes, dict):
        raise LicensePoolError("topology.nodes is required")
    try:
        resolved_nodes = effective_nodes(data)
    except TopologyError as error:
        raise LicensePoolError(str(error)) from error
    pools: list[tuple[str, str, str | None, str]] = []
    direct: dict[str, tuple[str, str]] = {}
    for node in resolved_nodes:
        if node.data.get("license") != contract.prompt_marker:
            continue
        node_name = node.name
        node_env = node.data.get("env", {})
        if node_env is None:
            node_env = {}
        if not isinstance(node_env, Mapping):
            raise LicensePoolError(f"node {node_name} env must be a YAML mapping")
        identity = node_env.get(UUID_ENVIRONMENT, node_name)
        if not isinstance(identity, str) or not identity:
            raise LicensePoolError(
                f"node {node_name} {UUID_ENVIRONMENT} must be a nonempty string"
            )
        claim = f"{workspace}:{identity}"
        key = contract.node_license_environment(node_name)
        value = environ.get(key) or environ.get(contract.license_environment)
        if not value and sys.stdin.isatty():
            value = input(
                f"License for {node_name} (file, pool directory, or $VARIABLE): "
            ).strip()
        if not value:
            raise LicensePoolError(
                f"frozen license for {node_name} requires {key}, {contract.license_environment}, or an interactive terminal"
            )
        if value.startswith("$"):
            variable = value[1:].strip("{}")
            value = environ.get(variable, "")
            if not value:
                raise LicensePoolError(
                    f"license variable {variable} is not set for node {node_name}"
                )
        candidate = Path(value).expanduser().resolve()
        if candidate.is_file():
            direct[node_name] = (claim, str(candidate))
        elif candidate.is_dir():
            pools.append((node_name, str(candidate), None, claim))
        else:
            raise LicensePoolError(
                f"frozen license choice for {node_name} is not a file or directory: {candidate}"
            )
    return pools, direct


def _load(state: Any) -> dict[str, Any]:
    if not state.exists(_FILE):
        return {"version": _STATE_VERSION, "pools": {}}
    value = json.loads(state.read_text(_FILE))
    if not isinstance(value, dict) or not isinstance(value.get("pools"), dict):
        raise LicensePoolError("invalid license-pool state")
    if value.get("version") == 1:
        _upgrade_state_v1(value)
    if value.get("version") != _STATE_VERSION:
        raise LicensePoolError("invalid license-pool state")
    for entry in value["pools"].values():
        _validate_pool_entry(entry)
    return value


def _claim(
    state: Any,
    requests: list[tuple[str, str, str | None, str]],
    strategy: LicenseStrategy | str = LicenseStrategy.LEAST_RECENTLY_USED,
) -> dict[str, str]:
    assigned, _created = _claim_with_created(state, requests, strategy)
    return assigned


def _claim_with_created(
    state: Any,
    requests: list[tuple[str, str, str | None, str]],
    strategy: LicenseStrategy | str = LicenseStrategy.LEAST_RECENTLY_USED,
) -> tuple[dict[str, str], tuple[tuple[str, str, str], ...]]:
    strategy = _coerce_strategy(strategy)
    with state.transaction() as locked:
        registry = _load(locked)
        out = {}
        created: list[tuple[str, str, str]] = []
        for _node, pool, clamp, claim in requests:
            entry = registry["pools"].setdefault(pool, _new_pool_entry())
            _validate_pool_entry(entry)
            allocations = entry["allocations"]
            history = entry["history"]
            # An empty file cannot carry a license; stray markers such as a
            # touched `.tst` would otherwise be claimed and served. Dotfiles are
            # skipped for the same reason: a pool directory accumulates editor
            # swapfiles, `.DS_Store`, and sync metadata that are not licenses.
            # The name is tested before resolving, so a dotfile symlinked to a
            # real license is still ignored -- name the target to use it.
            files = sorted(
                str(p.resolve()) for p in Path(pool).iterdir()
                if p.is_file() and not p.name.startswith(".") and p.stat().st_size > 0
            )
            if not files:
                raise LicensePoolError(f"license pool is empty: {pool}")
            existing = next(
                (path for path, owner in allocations.items() if owner == claim), None
            )
            if existing in files:
                _record_use(entry, existing)
                out[claim] = existing
                continue
            free = [path for path in files if path not in allocations]
            choice: str | None
            if clamp:
                target = (
                    str((Path(pool) / clamp).resolve())
                    if not Path(clamp).is_absolute()
                    else str(Path(clamp).resolve())
                )
                if target not in free:
                    raise LicensePoolError(f"clamped license is unavailable: {target}")
                choice = target
                entry["clamped"] = sorted(set(entry["clamped"] + [choice]))
            else:
                choice = _select_available(entry, files, free, history, claim, strategy)
                if choice is None:
                    raise LicensePoolError(f"no available licenses in pool {pool}")
            allocations[choice] = claim
            created.append((pool, choice, claim))
            history[choice] = claim
            _record_use(entry, choice)
            out[claim] = choice
        locked.write_text(_FILE, json.dumps(registry, sort_keys=True) + "\n")
        return out, tuple(created)


def _license_strategy(environ: Mapping[str, str]) -> LicenseStrategy:
    return _coerce_strategy(
        environ.get(
            LICENSE_POOL_STRATEGY_ENVIRONMENT,
            LicenseStrategy.LEAST_RECENTLY_USED.value,
        )
    )


def _coerce_strategy(value: LicenseStrategy | str) -> LicenseStrategy:
    try:
        return LicenseStrategy(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(strategy.value for strategy in LicenseStrategy)
        raise LicensePoolError(
            f"license pool strategy must be one of: {choices}"
        ) from error


def _new_pool_entry() -> dict[str, Any]:
    return {
        "allocations": {},
        "history": {},
        "clamped": [],
        "round_robin_index": 0,
        "last_used": {},
        "usage_sequence": 0,
    }


def _upgrade_state_v1(registry: dict[str, Any]) -> None:
    pools = registry["pools"]
    assert isinstance(pools, dict)
    for entry in pools.values():
        if not isinstance(entry, dict) or not isinstance(entry.get("history"), dict):
            raise LicensePoolError("invalid license-pool state")
        entry["round_robin_index"] = 0
        entry["last_used"] = {path: 0 for path in entry["history"]}
        entry["usage_sequence"] = 0
    registry["version"] = _STATE_VERSION


def _validate_pool_entry(entry: Any) -> None:
    if not isinstance(entry, dict):
        raise LicensePoolError("invalid license-pool state")
    mappings = (entry.get("allocations"), entry.get("history"))
    if any(
        not isinstance(mapping, dict)
        or any(
            not isinstance(path, str) or not isinstance(owner, str)
            for path, owner in mapping.items()
        )
        for mapping in mappings
    ):
        raise LicensePoolError("invalid license-pool state")
    clamped = entry.get("clamped")
    last_used = entry.get("last_used")
    if (
        not isinstance(clamped, list)
        or any(not isinstance(path, str) for path in clamped)
        or not isinstance(last_used, dict)
        or any(
            not isinstance(path, str) or type(sequence) is not int or sequence < 0
            for path, sequence in last_used.items()
        )
    ):
        raise LicensePoolError("invalid license-pool state")
    for field in ("round_robin_index", "usage_sequence"):
        value = entry.get(field)
        if type(value) is not int or value < 0:
            raise LicensePoolError("invalid license-pool state")
    if any(sequence > entry["usage_sequence"] for sequence in last_used.values()):
        raise LicensePoolError("invalid license-pool state")


def _select_available(
    entry: dict[str, Any],
    files: list[str],
    free: list[str],
    history: dict[str, str],
    claim: str,
    strategy: LicenseStrategy,
) -> str | None:
    if strategy is LicenseStrategy.STICKY:
        never = [path for path in free if path not in history]
        preferred = [
            path
            for path in free
            if history.get(path) == claim and path not in entry["clamped"]
        ]
        normal = [path for path in free if path not in entry["clamped"]]
        for candidates in (preferred, never, normal, free):
            if candidates:
                return candidates[0]
        return None

    available = [path for path in free if path not in entry["clamped"]] or free
    if not available:
        return None
    if strategy is LicenseStrategy.LEAST_RECENTLY_USED:
        last_used = cast(dict[str, int], entry["last_used"])
        return min(
            available,
            key=lambda path: (last_used.get(path, -1), path),
        )

    available_set = set(available)
    start = cast(int, entry["round_robin_index"]) % len(files)
    for offset in range(len(files)):
        index = (start + offset) % len(files)
        if files[index] in available_set:
            entry["round_robin_index"] = (index + 1) % len(files)
            return files[index]
    return None


def _record_use(entry: dict[str, Any], path: str) -> None:
    sequence = entry["usage_sequence"] + 1
    entry["usage_sequence"] = sequence
    entry["last_used"][path] = sequence


def _release_workspace(state: Any, workspace: str) -> None:
    with state.transaction() as locked:
        registry = _load(locked)
        for entry in registry["pools"].values():
            entry["allocations"] = {
                path: claim
                for path, claim in entry["allocations"].items()
                if not claim.startswith(workspace + ":")
            }
        locked.write_text(_FILE, json.dumps(registry, sort_keys=True) + "\n")


def _release_claims(state: Any, claims: tuple[tuple[str, str, str], ...]) -> None:
    if not claims:
        return
    with state.transaction() as locked:
        registry = _load(locked)
        for pool, path, claim in claims:
            entry = registry["pools"].get(pool)
            if isinstance(entry, dict) and entry["allocations"].get(path) == claim:
                del entry["allocations"][path]
        locked.write_text(_FILE, json.dumps(registry, sort_keys=True) + "\n")


def _warn_legacy_uuid(api: InvocationAPI, data: dict[str, Any]) -> None:
    """Warn about a topology still carrying the removed top-level `uuid:` field.

    Allocation identity moved to node ``env``. Staying silent would quietly change
    which license a node claims, so name the nodes and the replacement instead.
    """
    nodes = data.get("topology", {}).get("nodes", {})
    if not isinstance(nodes, dict):
        return
    stale = sorted(
        str(name)
        for name, node in nodes.items()
        if isinstance(node, dict) and "uuid" in node
    )
    if stale:
        api.logger.warning(
            "ignoring the removed node field 'uuid' on %s; "
            "move the value to env.%s to keep the same license allocation",
            ", ".join(stale),
            UUID_ENVIRONMENT,
        )


def _claimed_workspaces(state: Any) -> tuple[str, ...]:
    """Return every workspace root the registry currently records a claim for.

    Allocations are stored as ``"<workspace root>:<node>"``, matching the prefix
    match `_release_workspace` uses, so the root is everything before the last
    separator.
    """
    with state.transaction() as locked:
        registry = _load(locked)
        roots = {
            claim.rsplit(":", 1)[0]
            for entry in registry["pools"].values()
            for claim in entry["allocations"].values()
            if ":" in claim
        }
    return tuple(sorted(roots))


def _remove_license_copies(root: Path, contract: Any) -> None:
    """Delete only the copy directories this plugin creates inside one workspace."""
    for directory in (contract.state_directory, _LEGACY_STATE_DIRECTORY):
        shutil.rmtree(root / directory / "licenses", ignore_errors=True)


def _release_all(state: Any) -> None:
    with state.transaction() as locked:
        registry = _load(locked)
        for entry in registry["pools"].values():
            entry["allocations"] = {}
        locked.write_text(_FILE, json.dumps(registry, sort_keys=True) + "\n")


def _lease(pool: str) -> str:
    return "license-pool:" + hashlib.sha256(pool.encode()).hexdigest()


def _copy_to_lab(
    source: Path, lab_dir: Path, claim: str, contract: LicenseContract
) -> Path:
    target = _copy_path(lab_dir, claim, source.name, contract)
    target_dir = target.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def _copy_path(
    lab_dir: Path, claim: str, filename: str, contract: LicenseContract
) -> Path:
    return (
        lab_dir
        / contract.state_directory
        / "licenses"
        / hashlib.sha256(claim.encode()).hexdigest()
        / filename
    )


def _remove_empty_copy_parents(directory: Path) -> None:
    for candidate in (directory, directory.parent):
        try:
            candidate.rmdir()
        except OSError:
            break
