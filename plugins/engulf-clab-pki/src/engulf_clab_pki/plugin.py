from __future__ import annotations

import argparse
import hashlib
import importlib.resources
import json
import os
import posixpath
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml  # type: ignore[import-untyped]
from engulf_api import BeforeGoalAPI, GoalResult, Invocation, InvocationAPI, StateScope
from engulf_clab_lab_parser import (
    TOPOLOGY_CONTEXT,
    TopologyError,
    TopologySession,
    editor,
    effective_nodes,
    is_topology_mutation_command,
    load_topology,
    topology_declarations,
)
from engulf_clab_pki_api import PKI_NODE_PROJECTIONS_CONTEXT
from engulf_clab_schema_api import (
    SCHEMA_CONTEXTS,
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

from .catalog import (
    CatalogError,
    EffectiveCatalog,
    bind_topology_requests,
    load_catalog,
    merge_catalogs,
)
from .material import MaterialSet, generate_catalog, rollback_created
from .projections import build_node_projections
from .views import MOUNT_TARGET, build_views, cleanup_views, incompatible_mount

MANIFEST_ENVIRONMENT = "ECLAB_PKI_MANIFEST"
MOUNT_TARGET_ENVIRONMENT = "ECLAB_PKI_MOUNT_TARGET"
CERTIFICATES_ENVIRONMENT = "ECLAB_PKI_CERTIFICATES"
PRIVATE_AUTHORITIES_ENVIRONMENT = "ECLAB_PKI_PRIVATE_AUTHORITIES"
ROOT_ENVIRONMENT = "ECLAB_PKI_ROOT"
TRUST_ENVIRONMENTS = (
    "ECLAB_PKI_TRUST_MODE",
    "ECLAB_PKI_TRUST_INCLUDE",
    "ECLAB_PKI_TRUST_EXCLUDE",
)
_INVOCATION_CONTEXT = "engulf_clab.pki.invocation"

PLUGIN_SCHEMA = (
    PluginSchema("engulf_clab.pki", package="engulf_clab_pki")
    .add_node_var(
        MANIFEST_ENVIRONMENT,
        "Select a topology-relative PKI manifest and opt this topology into PKI mounts.",
        values=ValueType.FILE_PATH,
    )
    .add_node_var(
        MOUNT_TARGET_ENVIRONMENT,
        "Override the absolute in-container PKI mount target; node scope wins over defaults.",
        values=ValueType.STRING,
        default=MOUNT_TARGET,
    )
    .add_node_var(
        CERTIFICATES_ENVIRONMENT,
        "Request comma-separated named leaf certificates from the v2 PKI catalog.",
        values=ValueType.STRING,
    )
    .add_node_var(
        PRIVATE_AUTHORITIES_ENVIRONMENT,
        "Authorize comma-separated private CA identities for this node.",
        values=ValueType.STRING,
    )
    .add_node_var("ECLAB_PKI_TRUST_MODE", "Select natural anchors with all or start empty with none.", values=ValueType.STRING, default="all")
    .add_node_var("ECLAB_PKI_TRUST_INCLUDE", "Add comma-separated authority references to node trust.", values=ValueType.STRING)
    .add_node_var("ECLAB_PKI_TRUST_EXCLUDE", "Remove comma-separated authority references from node trust last.", values=ValueType.STRING)
    .add_command("pki", "Manage and inspect PKI catalogs without deploying a lab.")
    .add_cli_argument(
        "pki",
        "PKI_ACTION",
        "Run global path/init/edit/validate or effective -t TOPOLOGY.",
        values=ValueType.STRING,
    )
    .annotate(
        MANIFEST_ENVIRONMENT,
        commands=("deploy", "destroy", "freeze"),
        path_base=PathBase.TOPOLOGY_DIRECTORY,
        lifecycle=(LifecycleStage.PREPARE_CALL,),
        implies=("mount read-only PKI views at the node's resolved PKI target",),
    )
    .annotate(
        MOUNT_TARGET_ENVIRONMENT,
        commands=("deploy", "destroy", "freeze"),
        lifecycle=(LifecycleStage.PREPARE_CALL,),
        implies=("remove this control from the derived topology",),
    )
    .annotate(
        CERTIFICATES_ENVIRONMENT,
        commands=("deploy", "freeze"),
        lifecycle=(LifecycleStage.PREPARE_CALL,),
        requires=(MANIFEST_ENVIRONMENT,),
        implies=("issue every resolved named declaration and consume this control",),
    )
    .annotate(
        PRIVATE_AUTHORITIES_ENVIRONMENT,
        commands=("deploy", "freeze"),
        lifecycle=(LifecycleStage.PREPARE_CALL,),
        requires=(MANIFEST_ENVIRONMENT,),
        implies=("authorize every resolved CA keypair and consume this control",),
    )
    .annotate("pki", lifecycle=(LifecycleStage.BEFORE_GOAL,))
    .use_case("Generate persistent CA and node identities only for explicitly opted-in labs.")
    .reject("Do not install guest trust or expose private keys to unrequested nodes.")
    .order(
        LifecycleStage.PREPARE_CALL,
        "PKI reads the parsed source and injects mounts before final serialization.",
        after=("engulf_clab.lab_parser",),
        before=("engulf_clab.lab_writer", "engulf_clab.freeze"),
    )
    .route(
        "configure-pki",
        "USAGE.md",
        "Read catalog merge, generation, mount, persistence, and freeze behavior.",
    )
    .refer("USAGE.md")
)


@dataclass(frozen=True, slots=True)
class _Prepared:
    material: MaterialSet
    views: tuple[Path, ...]
    workspace_root: Path


class PkiPlugin(SchemaBackedPlugin):
    plugin_id = "engulf_clab.pki"
    schema = PLUGIN_SCHEMA
    priority = 40
    context_reads = (
        frozenset({TOPOLOGY_CONTEXT, _INVOCATION_CONTEXT, PKI_NODE_PROJECTIONS_CONTEXT})
        | SCHEMA_CONTEXTS
    )
    context_writes = (
        frozenset({_INVOCATION_CONTEXT, PKI_NODE_PROJECTIONS_CONTEXT}) | SCHEMA_CONTEXTS
    )

    def before_goal(self, invocation: Invocation, api: BeforeGoalAPI) -> GoalResult[object] | None:
        record_plugin_schema(api, PLUGIN_SCHEMA)
        if not invocation.arguments or invocation.arguments[0] != "pki":
            return None
        try:
            code = _pki_command(
                list(invocation.arguments[1:]),
                user_root=api.state(StateScope.USER).directory,
                cwd=invocation.cwd,
                environment=invocation.environment,
            )
        except (CatalogError, TopologyError, OSError, subprocess.SubprocessError) as error:
            api.logger.error("pki: %s", error)
            code = 1
        return GoalResult.completed(exit_code=code)

    def help(self, api: HelpAPI) -> str:
        del api
        return (
            "  pki global path|init|edit|validate   Manage the user PKI catalog\n"
            "  pki effective -t TOPOLOGY           Print merged origin-labelled PKI\n"
            f"  topology.defaults.env.{MANIFEST_ENVIRONMENT}: ./pki.yaml\n"
            f"  [defaults|kind|group|node].env.{MOUNT_TARGET_ENVIRONMENT}: {MOUNT_TARGET}\n"
            f"  [defaults|kind|group|node].env.{CERTIFICATES_ENVIRONMENT}: REF,...\n"
            f"  [defaults|kind|group|node].env.{PRIVATE_AUTHORITIES_ENVIRONMENT}: REF,...\n"
            "  ECLAB_PKI_TRUST_MODE=all|none with TRUST_INCLUDE/EXCLUDE=REF,...\n"
            "      Request named v2 identities and mount a node-specific read-only inventory\n"
            "  freeze --include-pki-secrets [--pki-passphrase-file FILE]\n"
            "  defrost --pki-authority BINDING=REF [--no-pki-prompt]"
        )

    def analyze_call(self, event: BeforeCallEvent, api: InvocationAPI) -> CallContribution | None:
        del event, api
        return None

    def prepare_call(self, event: PreparedCallEvent, api: InvocationAPI) -> None:
        if not is_topology_mutation_command(event.wrapper_args):
            return
        session = api.require_context(TOPOLOGY_CONTEXT)
        if not isinstance(session, TopologySession):
            raise CatalogError("invalid shared topology session")
        topology = session.materialize()
        selected = _manifest_selection(topology)
        if selected is None:
            return
        manifest = _resolve_manifest(session.path, selected)
        catalog = _effective(api.state(StateScope.USER).directory, manifest)
        topology_nodes = topology.get("topology", {}).get("nodes", {})
        if not isinstance(topology_nodes, dict):
            raise CatalogError("topology.nodes must be a mapping")
        bind_topology_requests(catalog, topology)
        services = _validated_services(catalog, topology_nodes)
        catalog.local_catalog["_topology_nodes"] = [*topology_nodes, *services.values()]
        mount_targets = _mount_targets(topology, topology_nodes)
        default_mount_target = _default_mount_target(topology)
        defaults = topology.get("topology", {}).get("defaults", {})
        default_environment = defaults.get("env", {}) if isinstance(defaults, dict) else {}
        if isinstance(default_environment, dict) and ROOT_ENVIRONMENT in default_environment:
            raise CatalogError(f"topology defaults define PKI-owned variable {ROOT_ENVIRONMENT}")
        for warning in catalog.warnings:
            api.logger.warning("%s", warning)
        resolved_nodes = {node.name: node for node in effective_nodes(topology)}
        for name, effective in resolved_nodes.items():
            environment = effective.data.get("env", {})
            if ROOT_ENVIRONMENT in environment:
                origin = effective.origin("env", ROOT_ENVIRONMENT)
                raise CatalogError(
                    f"node {name!r} inherits PKI-owned variable {ROOT_ENVIRONMENT} at {origin.path if origin else name}"
                )
            if incompatible_mount(effective.data, str(mount_targets[str(name)])):
                raise CatalogError(
                    f"node {name!r} already has an incompatible mount at {mount_targets[str(name)]}"
                )
        workspace = api.state(StateScope.WORKSPACE).directory
        material = MaterialSet({}, {}, [])
        created_views: list[Path] = []
        try:
            lease_names = tuple(
                sorted(
                    f"pki-authority:{scope}:{name}" for scope, name in _shared_authorities(catalog)
                )
            )
            with api.leases(lease_names):
                material = generate_catalog(
                    catalog,
                    user_root=api.state(StateScope.USER).directory,
                    workspace_root=workspace,
                )
            views, created_views = build_views(catalog, material, workspace)
            mutation = editor(api, self.plugin_id)
            for declaration in topology_declarations(topology):
                for variable in (MANIFEST_ENVIRONMENT, MOUNT_TARGET_ENVIRONMENT, CERTIFICATES_ENVIRONMENT, PRIVATE_AUTHORITIES_ENVIRONMENT, *TRUST_ENVIRONMENTS):
                    mutation.delete(declaration.field_origin("env", variable).path)
            for name, node in topology_nodes.items():
                node = node or {}
                effective = resolved_nodes[str(name)]
                binds = list(effective.data.get("binds") or ())
                target = mount_targets[str(name)]
                binds.append(f"{views[str(name)]}:{target}:ro")
                mutation.modify(("topology", "nodes", name, "binds"), binds)
                mutation.delete(("topology", "nodes", name, "env", MOUNT_TARGET_ENVIRONMENT))
                environment = node.get("env", {})
                if environment is None:
                    environment = {}
                filtered_environment = {
                    key: value
                    for key, value in environment.items()
                    if key
                    not in {
                        MOUNT_TARGET_ENVIRONMENT,
                        CERTIFICATES_ENVIRONMENT,
                        PRIVATE_AUTHORITIES_ENVIRONMENT,
                        *TRUST_ENVIRONMENTS,
                    }
                }
                mutation.modify(
                    ("topology", "nodes", name, "env"),
                    {**filtered_environment, ROOT_ENVIRONMENT: str(target)},
                )
            _inject_services(catalog, services, views, default_mount_target, mutation)
            prepared = _Prepared(material, tuple(created_views), workspace)
            projections = build_node_projections(catalog, material, topology, views, mount_targets)
            api.set_context(PKI_NODE_PROJECTIONS_CONTEXT, projections)
            # PKI owns the optional publication when no injector is installed.
            api.get_context(PKI_NODE_PROJECTIONS_CONTEXT)
            api.set_context(_INVOCATION_CONTEXT, prepared)
            _write_journal(workspace, prepared)
        except BaseException:
            cleanup_views(created_views)
            rollback_created(material.created)
            raise

    def prepare_failed(self, event: PreparationFailedEvent, api: InvocationAPI) -> None:
        if is_topology_mutation_command(event.wrapper_args):
            value = api.get_context(_INVOCATION_CONTEXT)
            if isinstance(value, _Prepared):
                _rollback(value)

    def after_call(self, event: AfterCallEvent, api: InvocationAPI) -> None:
        if not event.wrapper_args or event.mode is CallMode.HELP:
            return
        action = event.wrapper_args[0]
        value = api.get_context(_INVOCATION_CONTEXT)
        if is_topology_mutation_command(event.wrapper_args):
            if isinstance(value, _Prepared):
                succeeded = (
                    event.outcome.kind is OutcomeKind.COMPLETED
                    and event.outcome.exit_code == 0
                )
                if succeeded:
                    _clear_journal(value.workspace_root)
                elif not event.outcome.process_started:
                    _rollback(value)
                else:
                    api.logger.warning(
                        "retaining staged PKI after failed deploy for partial containers; "
                        "a successful destroy will clean it"
                    )
            return
        if (
            action == "destroy"
            and event.outcome.kind is OutcomeKind.COMPLETED
            and event.outcome.exit_code == 0
        ):
            workspace = api.state(StateScope.WORKSPACE).directory
            _reconcile_journal(workspace)
            views = workspace / "pki" / "views"
            if views.is_dir() and not views.is_symlink():
                shutil.rmtree(views)
            ephemeral = workspace / "pki" / "ephemeral"
            if ephemeral.is_dir() and not ephemeral.is_symlink():
                shutil.rmtree(ephemeral)


def _manifest_selection(topology: dict[str, Any]) -> str | None:
    defaults = topology.get("topology", {}).get("defaults", {})
    env = defaults.get("env", {}) if isinstance(defaults, dict) else {}
    value = env.get(MANIFEST_ENVIRONMENT) if isinstance(env, dict) else None
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise CatalogError(f"{MANIFEST_ENVIRONMENT} must be a nonempty path")
    return value


def _resolve_manifest(topology: Path, value: str) -> Path:
    candidate = Path(value).expanduser()
    return (candidate if candidate.is_absolute() else topology.parent / candidate).resolve()


def _default_mount_target(topology: dict[str, Any]) -> PurePosixPath:
    topology_block = topology.get("topology", {})
    defaults = topology_block.get("defaults", {}) if isinstance(topology_block, dict) else {}
    environment = defaults.get("env", {}) if isinstance(defaults, dict) else {}
    value = environment.get(MOUNT_TARGET_ENVIRONMENT) if isinstance(environment, dict) else None
    return _validate_mount_target(value, owner="topology defaults")


def _mount_targets(topology: dict[str, Any], nodes: dict[str, Any]) -> dict[str, PurePosixPath]:
    del nodes  # The shared resolver owns selection and inheritance.
    result: dict[str, PurePosixPath] = {}
    for node in effective_nodes(topology):
        environment = node.data.get("env", {})
        value = environment.get(MOUNT_TARGET_ENVIRONMENT)
        result[node.name] = _validate_mount_target(value, owner=f"node {node.name!r}")
    return result


def _validate_mount_target(value: Any, *, owner: str) -> PurePosixPath:
    if value is None:
        value = MOUNT_TARGET
    if not isinstance(value, str) or not value:
        raise CatalogError(f"{owner} {MOUNT_TARGET_ENVIRONMENT} must be a nonempty string")
    if (
        not value.startswith("/")
        or value == "/"
        or "//" in value
        or posixpath.normpath(value) != value
        or value.endswith("/")
        or any(part in {".", "..", "~"} for part in value.split("/"))
        or any(character in value for character in (":", ";", "\x00"))
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise CatalogError(
            f"{owner} {MOUNT_TARGET_ENVIRONMENT} must be a normalized absolute POSIX "
            "container path without bind or PKI-list delimiters"
        )
    return PurePosixPath(value)


def _global_path(user_root: Path) -> Path:
    return user_root / "global.yaml"


def _effective(user_root: Path, manifest: Path) -> EffectiveCatalog:
    return merge_catalogs(
        load_catalog(_global_path(user_root), global_scope=True),
        load_catalog(manifest, required=True),
    )


def _shared_authorities(catalog: EffectiveCatalog) -> set[tuple[str, str]]:
    result = {("global", name) for name in catalog.global_catalog.get("authorities", {})}
    for name, spec in catalog.local_catalog.get("authorities", {}).items():
        if isinstance(spec, dict) and (spec.get("store") or spec.get("lifetime") == "persistent"):
            result.add(("local", name))
    return result


def _pki_command(argv: list[str], *, user_root: Path, cwd: Path, environment: Any) -> int:
    parser = argparse.ArgumentParser(prog="eclab pki")
    sub = parser.add_subparsers(dest="scope", required=True)
    global_parser = sub.add_parser("global")
    global_parser.add_argument("action", choices=("path", "init", "edit", "validate"))
    effective = sub.add_parser("effective")
    effective.add_argument("-t", "--topology", required=True)
    args = parser.parse_args(argv)
    path = _global_path(user_root)
    if args.scope == "global":
        if args.action == "path":
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(path.parent, 0o700)
            print(path)
        elif args.action == "init":
            _global_init(path)
        elif args.action == "validate":
            load_catalog(path, required=True, global_scope=True)
            print(f"valid: {path}")
        else:
            _global_edit(path, environment)
        return 0
    topology = Path(args.topology).expanduser()
    topology = (topology if topology.is_absolute() else cwd / topology).resolve()
    document = load_topology(topology, environment)
    selector = _manifest_selection(document)
    if selector is None:
        raise CatalogError("topology has not opted into PKI")
    catalog = _effective(user_root, _resolve_manifest(topology, selector))
    bind_topology_requests(catalog, document)
    print(yaml.safe_dump(catalog.public_graph(), sort_keys=False), end="")
    return 0


def _global_init(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    content = """# Global PKI catalog. Local pki.yaml definitions shadow names here.\nversion: 2\n\ndefaults: {}\nprofiles: {}\nstores: {}\nauthorities: {}\ncertificates: {}\n"""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)


def _global_edit(path: Path, environment: Any) -> None:
    if not path.exists():
        _global_init(path)
    original = path.read_bytes()
    digest = hashlib.sha256(original).digest()
    editor_command = environment.get("VISUAL") or environment.get("EDITOR")
    if not editor_command:
        raise CatalogError("set VISUAL or EDITOR to edit the global PKI catalog")
    with tempfile.TemporaryDirectory(prefix=".pki-edit-", dir=path.parent) as directory:
        staged = Path(directory) / "global.yaml"
        staged.write_bytes(original)
        subprocess.run([*shlex.split(editor_command), str(staged)], check=True)
        load_catalog(staged, required=True, global_scope=True)
        if hashlib.sha256(path.read_bytes()).digest() != digest:
            raise CatalogError("global PKI catalog changed while it was being edited")
        os.chmod(staged, 0o600)
        staged.replace(path)


def _validated_services(catalog: EffectiveCatalog, nodes: dict[str, Any]) -> dict[str, str]:
    claimed = set(nodes)
    result: dict[str, str] = {}
    for service, spec in catalog.services.items():
        node = spec.get("node")
        if not isinstance(node, str) or not node:
            raise CatalogError(f"service {service!r} requires an explicit node name")
        if node in claimed:
            raise CatalogError(f"PKI service node collides with topology node {node!r}")
        kind = str(spec.get("type", service))
        if kind == "ejbca" and isinstance(spec.get("authority"), str):
            scope, name, variant, authority = catalog.resolve_authority(spec["authority"])
            del scope, name
            if variant != "default":
                raise CatalogError("EJBCA services import only an authority's default chain")
            algorithm = authority.get("algorithm", "rsa")
            algorithm_name = (
                algorithm if isinstance(algorithm, str) else algorithm.get("name", "rsa")
            )
            if str(algorithm_name).lower() in {"ml-dsa", "mldsa"}:
                raise CatalogError("EJBCA-owned ML-DSA authorities are not supported")
        claimed.add(node)
        result[service] = node
    return result


def _inject_services(
    catalog: EffectiveCatalog,
    service_nodes: dict[str, str],
    views: dict[str, Path],
    mount_target: PurePosixPath,
    mutation: Any,
) -> None:
    recipe_file = importlib.resources.files("engulf_clab_pki").joinpath("recipes/services.yaml")
    recipes = yaml.safe_load(recipe_file.read_text(encoding="utf-8"))
    if not isinstance(recipes, dict):
        raise CatalogError("packaged PKI service recipes are invalid")
    for service, spec in catalog.services.items():
        kind = str(spec.get("type", service))
        node = service_nodes[service]
        recipe = recipes.get(kind, {})
        image = spec.get("image", recipe.get("image") if isinstance(recipe, dict) else None)
        if not isinstance(image, str):
            raise CatalogError(f"service {service!r} requires an image")
        definition: dict[str, Any] = {
            "kind": str(recipe.get("kind", "linux")) if isinstance(recipe, dict) else "linux",
            "image": image,
            "binds": [f"{views[node]}:{mount_target}:ro"],
        }
        service_environment = spec.get("env", {})
        if service_environment is None:
            service_environment = {}
        if not isinstance(service_environment, dict):
            raise CatalogError(f"service {service!r} env must be a mapping")
        if ROOT_ENVIRONMENT in service_environment:
            raise CatalogError(
                f"service {service!r} defines PKI-owned variable {ROOT_ENVIRONMENT}"
            )
        definition["env"] = {
            **service_environment,
            ROOT_ENVIRONMENT: str(mount_target),
        }
        mutation.add(("topology", "nodes", node), definition)


def _journal_path(workspace: Path) -> Path:
    return workspace / "pki" / "provisioning.json"


def _write_journal(workspace: Path, prepared: _Prepared) -> None:
    path = _journal_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    staged = path.with_suffix(".tmp")
    staged.write_text(
        json.dumps(
            {
                "views": [str(item) for item in prepared.views],
                "created": [str(item) for item in prepared.material.created],
            }
        ),
        encoding="utf-8",
    )
    staged.replace(path)


def _clear_journal(workspace: Path) -> None:
    _journal_path(workspace).unlink(missing_ok=True)


def _reconcile_journal(workspace: Path) -> None:
    path = _journal_path(workspace)
    if not path.is_file():
        return
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        cleanup_views([Path(item) for item in value.get("views", [])])
        rollback_created([Path(item) for item in value.get("created", [])])
    finally:
        path.unlink(missing_ok=True)


def _rollback(prepared: _Prepared) -> None:
    cleanup_views(list(prepared.views))
    rollback_created(prepared.material.created)
    _clear_journal(prepared.workspace_root)
