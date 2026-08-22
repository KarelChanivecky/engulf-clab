from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
    LifecycleStage,
    PathBase,
    PluginSchema,
    ValueType,
    record_plugin_schema,
)
from engulf_executable_wrapper_api import (
    AfterCallEvent,
    BeforeCallEvent,
    CallContribution,
    CallMode,
    ExecutableWrapperPlugin,
    HelpAPI,
    OutcomeKind,
    PreparedCallEvent,
)

_FILE = "license-pools.json"
_NON_ALPHANUMERIC = re.compile(r"[^A-Z0-9]+")
_LEGACY_STATE_DIRECTORY = ".engulf-clab"

# Fixed across every edition, matching engulf-clab-wan's LABEL_PREFIX
# convention: topology labels/env vars must stay portable regardless of the
# active application's product metadata. Unlike labels, the topology-local
# state directory below is deliberately still derived from application
# metadata, so every edition's state converges on the same directory as long
# as they share the same short_product_name.
LABEL_PREFIX = "ECLAB"


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
        "ECLAB_LICENSE",
        "Provide the default non-interactive frozen-lab license source.",
        values=(ValueType.FILE_PATH, ValueType.DIRECTORY_PATH, ValueType.STRING),
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
        "ECLAB_LICENSE",
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


class LicensePoolPlugin(ExecutableWrapperPlugin):
    plugin_id = "engulf_clab.license_pool"
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
            f"    {contract.license_environment}[_NODE]        Non-interactive value for a frozen license prompt\n"
            "  Pools contain top-level regular files and are leased across workspaces.\n"
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
        requests = _requests(topology, os.environ, workspace, contract)
        prompt_requests, direct = _prompt_requests(
            topology, os.environ, workspace, contract
        )
        requests.extend(prompt_requests)
        if not requests and not direct:
            return
        with api.leases(
            tuple(sorted({_lease(pool) for _node, pool, _clamp, _claim in requests}))
        ):
            state = api.state(StateScope.USER)
            assigned = _claim(state, requests)
        assigned.update({claim: source for claim, source in direct.values()})
        mutation = editor(api, self.plugin_id)
        for node, _pool, _clamp, claim in requests:
            copied = _copy_to_lab(
                Path(assigned[claim]), session.path.parent, claim, contract
            )
            mutation.modify(("topology", "nodes", node, "license"), str(copied))
        for node, (claim, _source) in direct.items():
            copied = _copy_to_lab(
                Path(assigned[claim]), session.path.parent, claim, contract
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
    environ: dict[str, str],
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
    environ: dict[str, str],
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
        return {"version": 1, "pools": {}}
    value = json.loads(state.read_text(_FILE))
    if (
        not isinstance(value, dict)
        or value.get("version") != 1
        or not isinstance(value.get("pools"), dict)
    ):
        raise LicensePoolError("invalid license-pool state")
    return value


def _claim(
    state: Any, requests: list[tuple[str, str, str | None, str]]
) -> dict[str, str]:
    with state.transaction() as locked:
        registry = _load(locked)
        out = {}
        for _node, pool, clamp, claim in requests:
            entry = registry["pools"].setdefault(
                pool, {"allocations": {}, "history": {}, "clamped": []}
            )
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
                out[claim] = existing
                continue
            free = [path for path in files if path not in allocations]
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
                never = [path for path in free if path not in history]
                preferred = [
                    path
                    for path in free
                    if history.get(path) == claim and path not in entry["clamped"]
                ]
                normal = [path for path in free if path not in entry["clamped"]]
                choice = (never or preferred or normal or free or [None])[0]
                if choice is None:
                    raise LicensePoolError(f"no available licenses in pool {pool}")
            allocations[choice] = claim
            history[choice] = claim
            out[claim] = choice
        locked.write_text(_FILE, json.dumps(registry, sort_keys=True) + "\n")
        return out


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
