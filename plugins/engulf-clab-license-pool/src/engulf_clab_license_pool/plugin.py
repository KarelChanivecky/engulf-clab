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
from typing import Any, cast

from engulf_api import (
    ApplicationMetadata,
    BeforeGoalAPI,
    DependencyPosition,
    GoalResult,
    Invocation,
    InvocationAPI,
    PluginDependency,
    StateScope,
)
from engulf_clab_lab_parser import TOPOLOGY_CONTEXT, TopologySession, editor
from engulf_clab_schema_api import (
    SCHEMA_CONTEXTS,
    SCHEMA_PLUGIN_DEPENDENCY,
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
    PreparedCallEvent,
)

_FILE = "license-pools.json"
_STATE_VERSION = 2
_NON_ALPHANUMERIC = re.compile(r"[^A-Z0-9]+")
_LEGACY_STATE_DIRECTORY = ".engulf-clab"

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
        "Select a license pool with $NAME or request a frozen-lab license prompt.",
        values=ValueType.STRING,
    )
    .add_node_prop(
        "uuid",
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
        default=LicenseStrategy.STICKY.value,
    )
    .add_cli_flag(
        "--eclab-license-pool-strategy",
        "Select the license-pool allocation strategy for this invocation.",
        values=_STRATEGY_VALUES,
        default=LicenseStrategy.STICKY.value,
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
        ),
        implies=(
            "a successful deploy copies the selected license into lab-local state",
        ),
        examples=("$ROUTER_LICENSE_POOL", "__ECLAB_LICENSE_PROMPT__"),
    )
    .annotate(
        "uuid",
        commands=("deploy",),
        implies=("stable allocation identity across node renames",),
    )
    .annotate(
        "ECLAB_LIC_CLAMP",
        commands=("deploy",),
        requires=("license selects a $POOL",),
        path_base=PathBase.LICENSE_POOL,
    )
    .annotate(
        "--eclab-license-pool-strategy",
        commands=("deploy",),
        lifecycle=(LifecycleStage.PREPARE_CALL,),
        implies=("active claims remain stable for deployment retries",),
    )
    .annotate(
        LICENSE_POOL_STRATEGY_ENVIRONMENT,
        commands=("deploy",),
        lifecycle=(LifecycleStage.PREPARE_CALL,),
        implies=("used when --eclab-license-pool-strategy is absent",),
    )
    .annotate(
        "ECLAB_LICENSE",
        commands=("deploy",),
        requires=("license is __ECLAB_LICENSE_PROMPT__",),
        path_base=PathBase.INVOCATION_DIRECTORY,
    )
    .annotate(
        "--eclab-license",
        commands=("deploy",),
        requires=("license is __ECLAB_LICENSE_PROMPT__",),
        path_base=PathBase.INVOCATION_DIRECTORY,
    )
    .annotate(
        "ECLAB_LICENSE_*",
        commands=("deploy",),
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
        "README.md",
        "Read pool selection, stable identity, prompts, leases, and cleanup.",
    )
    .refer("README.md")
    .refer("AGENTS.md")
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
    plugin_dependencies = (
        PluginDependency(
            "engulf_clab.lab_parser",
            preprocess=DependencyPosition.BEFORE,
            postprocess=None,
        ),
        PluginDependency(
            "engulf_clab.lab_writer",
            preprocess=DependencyPosition.AFTER,
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

    def help(self, api: HelpAPI) -> str:
        api.logger.debug("rendering license-pool help")
        contract = license_contract(api.application)
        return (
            "  Node YAML fields:\n"
            "    license: $POOL              Allocate from invocation environment POOL directory\n"
            "    uuid: <stable-uuid>         Recommended stable allocation identity\n"
            f"    env.{contract.clamp_environment}: file   Require this available pool filename/path\n"
            f"    license: {contract.prompt_marker}  Prompt for a file, pool, or $VARIABLE in frozen labs\n"
            "  --eclab-license-pool-strategy STRATEGY\n"
            "      sticky (default), round-robin, or least-recently-used\n"
            f"  {LICENSE_POOL_STRATEGY_ENVIRONMENT} is the persistent strategy default; CLI wins.\n"
            "  --eclab-license VALUE        Default non-interactive frozen-lab license\n"
            f"  {contract.license_environment} is the persistent environment default; "
            "--eclab-license wins.\n"
            f"  {contract.license_environment}_<NODE> remains the per-node prompt override.\n"
            "  Pools contain top-level regular files and are leased across workspaces.\n"
            "  Deploy logs each selected license basename with its node; source paths stay private.\n"
            "  Successful destroy releases claims and removes copied lab licenses."
        )

    def analyze_call(
        self, event: BeforeCallEvent, api: InvocationAPI
    ) -> CallContribution | None:
        return None

    def prepare_call(self, event: PreparedCallEvent, api: InvocationAPI) -> None:
        if not event.wrapper_args or event.wrapper_args[0] != "deploy":
            return
        session = api.require_context(TOPOLOGY_CONTEXT)
        if not isinstance(session, TopologySession):
            raise LicensePoolError("invalid shared topology session")
        topology = session.original_document()
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
            assigned = _claim(state, requests, strategy)
        assigned.update({claim: source for claim, source in direct.values()})
        mutation = editor(api, self.plugin_id)
        selections = [(node, claim) for node, _pool, _clamp, claim in requests]
        selections.extend((node, claim) for node, (claim, _source) in direct.items())
        for node, claim in selections:
            source = Path(assigned[claim])
            copied = _copy_to_lab(source, session.path.parent, claim, contract)
            api.logger.info(
                "selected license basename=%r for node=%r",
                source.name,
                node,
            )
            mutation.modify(("topology", "nodes", node, "license"), str(copied))

    def after_call(self, event: AfterCallEvent, api: InvocationAPI) -> None:
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
            if any(value in {"-a", "--all"} for value in event.wrapper_args[1:]):
                _release_all(state)
                return
            workspace = api.state(StateScope.WORKSPACE)
            _release_workspace(state, str(workspace.root))
            contract = license_contract(api.application)
            shutil.rmtree(
                workspace.root / contract.state_directory / "licenses",
                ignore_errors=True,
            )
            shutil.rmtree(
                workspace.root / _LEGACY_STATE_DIRECTORY / "licenses",
                ignore_errors=True,
            )


def _requests(
    data: dict[str, Any],
    environ: Mapping[str, str],
    workspace: Path,
    contract: LicenseContract,
) -> list[tuple[str, str, str | None, str]]:
    nodes = data.get("topology", {}).get("nodes", {})
    if not isinstance(nodes, dict):
        raise LicensePoolError("topology.nodes is required")
    result = []
    for name, node in nodes.items():
        if (
            not isinstance(node, dict)
            or not isinstance(node.get("license"), str)
            or not node["license"].startswith("$")
        ):
            continue
        pool_name = node["license"][1:]
        if not pool_name or pool_name not in environ:
            raise LicensePoolError(f"license pool ${pool_name} is not set")
        pool = Path(environ[pool_name]).expanduser().resolve()
        if not pool.is_dir():
            raise LicensePoolError(
                f"license pool ${pool_name} is not a directory: {pool}"
            )
        env = node.get("env", {})
        clamp = env.get(contract.clamp_environment) if isinstance(env, dict) else None
        if clamp is not None and not isinstance(clamp, str):
            raise LicensePoolError(
                f"node {name} {contract.clamp_environment} must be a string"
            )
        identity = node.get("uuid", name)
        if not isinstance(identity, str) or not identity:
            raise LicensePoolError(f"node {name} uuid must be a nonempty string")
        result.append((str(name), str(pool), clamp, f"{workspace}:{identity}"))
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
    pools: list[tuple[str, str, str | None, str]] = []
    direct: dict[str, tuple[str, str]] = {}
    for name, node in nodes.items():
        if not isinstance(node, dict) or node.get("license") != contract.prompt_marker:
            continue
        node_name = str(name)
        identity = node.get("uuid", node_name)
        if not isinstance(identity, str) or not identity:
            raise LicensePoolError(f"node {node_name} uuid must be a nonempty string")
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
    strategy: LicenseStrategy | str = LicenseStrategy.STICKY,
) -> dict[str, str]:
    strategy = _coerce_strategy(strategy)
    with state.transaction() as locked:
        registry = _load(locked)
        out = {}
        for _node, pool, clamp, claim in requests:
            entry = registry["pools"].setdefault(pool, _new_pool_entry())
            _validate_pool_entry(entry)
            allocations = entry["allocations"]
            history = entry["history"]
            files = sorted(
                str(p.resolve()) for p in Path(pool).iterdir() if p.is_file()
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
            history[choice] = claim
            _record_use(entry, choice)
            out[claim] = choice
        locked.write_text(_FILE, json.dumps(registry, sort_keys=True) + "\n")
        return out


def _license_strategy(environ: Mapping[str, str]) -> LicenseStrategy:
    return _coerce_strategy(
        environ.get(
            LICENSE_POOL_STRATEGY_ENVIRONMENT,
            LicenseStrategy.STICKY.value,
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
        for candidates in (never, preferred, normal, free):
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
    target_dir = (
        lab_dir
        / contract.state_directory
        / "licenses"
        / hashlib.sha256(claim.encode()).hexdigest()
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    shutil.copy2(source, target)
    return target
