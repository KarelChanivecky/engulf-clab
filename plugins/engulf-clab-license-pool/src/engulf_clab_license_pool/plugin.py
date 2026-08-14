from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from engulf_api import DependencyPosition, InvocationAPI, PluginDependency, StateScope
from engulf_clab_lab_parser import TOPOLOGY_CONTEXT, TopologySession, editor
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
_PROMPT = "__ECLAB_LICENSE_PROMPT__"
class LicensePoolError(RuntimeError): pass
class LicensePoolPlugin(ExecutableWrapperPlugin):
    plugin_id = "engulf_clab.license_pool"; priority = 60
    plugin_dependencies = (PluginDependency("engulf_clab.lab_parser", preprocess=DependencyPosition.BEFORE, postprocess=None), PluginDependency("engulf_clab.lab_writer", preprocess=DependencyPosition.AFTER, postprocess=None))
    context_reads = frozenset({TOPOLOGY_CONTEXT})
    def help(self, api: HelpAPI) -> str:
        api.logger.debug("rendering license-pool help")
        return (
            "  Node YAML fields:\n"
            "    license: $POOL              Allocate from invocation environment POOL directory\n"
            "    uuid: <stable-uuid>         Recommended stable allocation identity\n"
            "    env.ECLAB_LIC_CLAMP: file   Require this available pool filename/path\n"
            f"    license: {_PROMPT}  Prompt for a file, pool, or $VARIABLE in frozen labs\n"
            "    ECLAB_LICENSE[_NODE]        Non-interactive value for a frozen license prompt\n"
            "  Pools contain top-level regular files and are leased across workspaces.\n"
            "  Successful destroy releases claims and removes copied lab licenses."
        )
    def analyze_call(self, event: BeforeCallEvent, api: InvocationAPI) -> CallContribution | None: return None
    def prepare_call(self, event: PreparedCallEvent, api: InvocationAPI) -> None:
        if not event.wrapper_args or event.wrapper_args[0] != "deploy": return
        session = api.require_context(TOPOLOGY_CONTEXT)
        if not isinstance(session, TopologySession): raise LicensePoolError("invalid shared topology session")
        topology = session.original_document()
        workspace = api.state(StateScope.WORKSPACE).root
        requests = _requests(topology, os.environ, workspace)
        prompt_requests, direct = _prompt_requests(topology, os.environ, workspace)
        requests.extend(prompt_requests)
        if not requests and not direct: return
        with api.leases(tuple(sorted({_lease(pool) for _node, pool, _clamp, _claim in requests}))):
            state = api.state(StateScope.USER)
            assigned = _claim(state, requests)
        assigned.update({claim: source for claim, source in direct.values()})
        mutation = editor(api, self.plugin_id)
        for node, _pool, _clamp, claim in requests:
            copied = _copy_to_lab(Path(assigned[claim]), session.path.parent, claim)
            mutation.modify(("topology", "nodes", node, "license"), str(copied))
        for node, (claim, _source) in direct.items():
            copied = _copy_to_lab(Path(assigned[claim]), session.path.parent, claim)
            mutation.modify(("topology", "nodes", node, "license"), str(copied))
    def after_call(self, event: AfterCallEvent, api: InvocationAPI) -> None:
        if not event.wrapper_args or event.wrapper_args[0] != "destroy" or event.mode is CallMode.HELP: return
        if event.outcome.kind is not OutcomeKind.COMPLETED or event.outcome.exit_code: return
        with api.lease("license-pool-registry"):
            state = api.state(StateScope.USER)
            if any(value in {"-a", "--all"} for value in event.wrapper_args[1:]): _release_all(state); return
            workspace = api.state(StateScope.WORKSPACE)
            _release_workspace(state, str(workspace.root))
            shutil.rmtree(workspace.root / ".engulf-clab" / "licenses", ignore_errors=True)
def _requests(data: dict[str, Any], environ: dict[str, str], workspace: Path) -> list[tuple[str, str, str | None, str]]:
    nodes = data.get("topology", {}).get("nodes", {})
    if not isinstance(nodes, dict): raise LicensePoolError("topology.nodes is required")
    result=[]
    for name, node in nodes.items():
        if not isinstance(node, dict) or not isinstance(node.get("license"), str) or not node["license"].startswith("$"): continue
        pool_name=node["license"][1:]
        if not pool_name or pool_name not in environ: raise LicensePoolError(f"license pool ${pool_name} is not set")
        pool=Path(environ[pool_name]).expanduser().resolve()
        if not pool.is_dir(): raise LicensePoolError(f"license pool ${pool_name} is not a directory: {pool}")
        env=node.get("env", {}); clamp=env.get("ECLAB_LIC_CLAMP") if isinstance(env, dict) else None
        if clamp is not None and not isinstance(clamp, str): raise LicensePoolError(f"node {name} ECLAB_LIC_CLAMP must be a string")
        identity=node.get("uuid", name)
        if not isinstance(identity, str) or not identity: raise LicensePoolError(f"node {name} uuid must be a nonempty string")
        result.append((str(name), str(pool), clamp, f"{workspace}:{identity}"))
    return result
def _prompt_requests(data: dict[str, Any], environ: dict[str, str], workspace: Path) -> tuple[list[tuple[str, str, str | None, str]], dict[str, tuple[str, str]]]:
    nodes=data.get("topology", {}).get("nodes", {})
    if not isinstance(nodes, dict): raise LicensePoolError("topology.nodes is required")
    pools: list[tuple[str,str,str|None,str]]=[]; direct: dict[str,tuple[str,str]]={}
    for name,node in nodes.items():
        if not isinstance(node,dict) or node.get("license") != _PROMPT: continue
        node_name=str(name); identity=node.get("uuid", node_name)
        if not isinstance(identity,str) or not identity: raise LicensePoolError(f"node {node_name} uuid must be a nonempty string")
        claim=f"{workspace}:{identity}"; key="ECLAB_LICENSE_"+"".join(character if character.isalnum() else "_" for character in node_name.upper())
        value=environ.get(key) or environ.get("ECLAB_LICENSE")
        if not value and sys.stdin.isatty():
            value=input(f"License for {node_name} (file, pool directory, or $VARIABLE): ").strip()
        if not value: raise LicensePoolError(f"frozen license for {node_name} requires {key}, ECLAB_LICENSE, or an interactive terminal")
        if value.startswith("$"):
            variable=value[1:].strip("{}")
            value=environ.get(variable, "")
            if not value: raise LicensePoolError(f"license variable {variable} is not set for node {node_name}")
        candidate=Path(value).expanduser().resolve()
        if candidate.is_file(): direct[node_name]=(claim,str(candidate))
        elif candidate.is_dir(): pools.append((node_name,str(candidate),None,claim))
        else: raise LicensePoolError(f"frozen license choice for {node_name} is not a file or directory: {candidate}")
    return pools,direct
def _load(state: Any) -> dict[str, Any]:
    if not state.exists(_FILE): return {"version":1,"pools":{}}
    value=json.loads(state.read_text(_FILE))
    if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("pools"),dict): raise LicensePoolError("invalid license-pool state")
    return value
def _claim(state: Any, requests: list[tuple[str,str,str|None,str]]) -> dict[str,str]:
    with state.transaction() as locked:
        registry=_load(locked); out={}
        for _node,pool,clamp,claim in requests:
            entry=registry["pools"].setdefault(pool,{"allocations":{},"history":{},"clamped":[]}); allocations=entry["allocations"]; history=entry["history"]
            files=sorted(str(p.resolve()) for p in Path(pool).iterdir() if p.is_file())
            if not files: raise LicensePoolError(f"license pool is empty: {pool}")
            existing=next((path for path, owner in allocations.items() if owner == claim),None)
            if existing in files: out[claim]=existing; continue
            free=[path for path in files if path not in allocations]
            if clamp:
                target=str((Path(pool)/clamp).resolve()) if not Path(clamp).is_absolute() else str(Path(clamp).resolve())
                if target not in free: raise LicensePoolError(f"clamped license is unavailable: {target}")
                choice=target; entry["clamped"]=sorted(set(entry["clamped"]+[choice]))
            else:
                never=[path for path in free if path not in history]
                preferred=[path for path in free if history.get(path)==claim and path not in entry["clamped"]]
                normal=[path for path in free if path not in entry["clamped"]]
                choice=(never or preferred or normal or free or [None])[0]
                if choice is None: raise LicensePoolError(f"no available licenses in pool {pool}")
            allocations[choice]=claim; history[choice]=claim; out[claim]=choice
        locked.write_text(_FILE,json.dumps(registry,sort_keys=True)+"\n")
        return out
def _release_workspace(state: Any, workspace: str) -> None:
    with state.transaction() as locked:
        registry=_load(locked)
        for entry in registry["pools"].values(): entry["allocations"]={path:claim for path,claim in entry["allocations"].items() if not claim.startswith(workspace+":")}
        locked.write_text(_FILE,json.dumps(registry,sort_keys=True)+"\n")
def _release_all(state: Any) -> None:
    with state.transaction() as locked:
        registry=_load(locked)
        for entry in registry["pools"].values(): entry["allocations"]={}
        locked.write_text(_FILE,json.dumps(registry,sort_keys=True)+"\n")
def _lease(pool: str) -> str: return "license-pool:"+hashlib.sha256(pool.encode()).hexdigest()
def _copy_to_lab(source: Path, lab_dir: Path, claim: str) -> Path:
    target_dir = lab_dir / ".engulf-clab" / "licenses" / hashlib.sha256(claim.encode()).hexdigest()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    shutil.copy2(source, target)
    return target
