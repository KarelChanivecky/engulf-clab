from __future__ import annotations

from pathlib import Path
from typing import Any

from engulf_api import BeforeGoalAPI, Invocation, InvocationAPI
from engulf_clab_lab_parser import (
    TOPOLOGY_CONTEXT,
    TopologySession,
    is_topology_mutation_command,
)
from engulf_clab_pki_api import (
    PKI_NODE_PROJECTIONS_CONTEXT,
    NodePkiProjection,
    PkiNodeProjections,
    ProjectedFile,
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
    HelpAPI,
    PreparedCallEvent,
)

FORTIGATE_KIND = "fortinet_fortigate"
CA_CERTIFICATES = "FOS_PKI_CA_CERTS"
LOCAL_CERTIFICATES = "FOS_PKI_LOCAL_CERTS"
LOCAL_CERTIFICATE_PASSWORD_FILES = "FOS_PKI_LOCAL_CERT_PASS_FILES"
REMOTE_CERTIFICATES = "FOS_PKI_REMOTE_CERTS"
CRLS = "FOS_PKI_CRLS"
OWNED_ENVIRONMENT = frozenset(
    {
        CA_CERTIFICATES,
        LOCAL_CERTIFICATES,
        LOCAL_CERTIFICATE_PASSWORD_FILES,
        REMOTE_CERTIFICATES,
        CRLS,
    }
)


class InjectorError(RuntimeError):
    pass


PLUGIN_SCHEMA = (
    PluginSchema(
        "engulf_clab.vrnetlab_fortigate_pki_injector",
        package="engulf_clab_vrnetlab_fortigate_pki_injector",
    )
    .use_case("Install authorized PKI projections into PKI-enabled FortiGate vrnetlab nodes.")
    .reject("Do not set injector-owned FOS_PKI_* variables or use this for another node kind.")
    .order(
        LifecycleStage.PREPARE_CALL,
        "Translate staged PKI paths after PKI and before final topology serialization.",
        after=("engulf_clab.lab_parser", "engulf_clab.pki"),
        before=("engulf_clab.lab_writer",),
    )
    .route(
        "inject-fortigate-pki",
        "USAGE.md",
        "Read automatic FortiGate PKI path injection, collision, and lifecycle behavior.",
    )
    .refer("USAGE.md")
)


class FortigatePkiInjector(SchemaBackedPlugin):
    plugin_id = "engulf_clab.vrnetlab_fortigate_pki_injector"
    schema = PLUGIN_SCHEMA
    priority = 30
    context_reads = frozenset({TOPOLOGY_CONTEXT, PKI_NODE_PROJECTIONS_CONTEXT}) | SCHEMA_CONTEXTS
    context_writes = SCHEMA_CONTEXTS

    def before_goal(self, invocation: Invocation, api: BeforeGoalAPI) -> None:
        del invocation
        record_plugin_schema(api, PLUGIN_SCHEMA)

    def help(self, api: HelpAPI) -> str:
        del api
        return (
            "  FortiGate PKI injection (automatic when PKI is selected)\n"
            "      Generates mandatory-refname FOS_PKI_CA_CERTS and FOS_PKI_LOCAL_CERTS entries\n"
            "      Existing injector-owned FOS_PKI_* variables are rejected"
        )

    def analyze_call(self, event: BeforeCallEvent, api: InvocationAPI) -> CallContribution | None:
        del event, api
        return None

    def prepare_call(self, event: PreparedCallEvent, api: InvocationAPI) -> None:
        if not is_topology_mutation_command(event.wrapper_args):
            return
        value = api.get_context(PKI_NODE_PROJECTIONS_CONTEXT)
        if value is None:
            return
        if not isinstance(value, PkiNodeProjections):
            raise InjectorError("invalid PKI node projection context")
        session = api.require_context(TOPOLOGY_CONTEXT)
        if not isinstance(session, TopologySession):
            raise InjectorError("invalid shared topology session")
        topology = session.materialize()
        topology_block = topology.get("topology", {})
        if not isinstance(topology_block, dict):
            raise InjectorError("topology must be a mapping")
        nodes = topology_block.get("nodes", {})
        defaults = topology_block.get("defaults", {})
        if not isinstance(nodes, dict):
            raise InjectorError("topology.nodes must be a mapping")
        mutation = session.editor(self.plugin_id)
        for projection in value.nodes:
            node = nodes.get(projection.node_name)
            if node is None:
                continue
            if not isinstance(node, dict):
                raise InjectorError(
                    f"projected PKI node {projection.node_name!r} must be a mapping"
                )
            kind = _node_kind(node, defaults)
            if kind != projection.node_kind:
                raise InjectorError(
                    f"node {projection.node_name!r} kind does not match its PKI projection"
                )
            if kind != FORTIGATE_KIND:
                continue
            _validate_projection(projection, node)
            environment = _environment(node, owner=f"node {projection.node_name!r}")
            _reject_collisions(projection.node_name, environment, defaults)
            generated = _environment_values(projection)
            for variable, generated_value in generated.items():
                mutation.modify(
                    ("topology", "nodes", projection.node_name, "env", variable),
                    generated_value,
                )


def _node_kind(node: dict[str, Any], defaults: Any) -> str:
    value = node.get("kind")
    if value is None and isinstance(defaults, dict):
        value = defaults.get("kind")
    return "linux" if value is None else str(value)


def _environment(mapping: dict[str, Any], *, owner: str) -> dict[str, Any]:
    value = mapping.get("env", {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise InjectorError(f"{owner} env must be a mapping")
    return dict(value)


def _reject_collisions(node_name: str, node_environment: dict[str, Any], defaults: Any) -> None:
    default_environment = (
        _environment(defaults, owner="topology defaults") if isinstance(defaults, dict) else {}
    )
    for variable in sorted(OWNED_ENVIRONMENT):
        if variable in node_environment:
            raise InjectorError(
                f"node {node_name!r} already defines injector-owned variable {variable} in node env"
            )
        if variable in default_environment:
            raise InjectorError(
                f"node {node_name!r} already defines injector-owned variable {variable} "
                "in topology defaults"
            )


def _validate_projection(projection: NodePkiProjection, node: dict[str, Any]) -> None:
    if projection.staged_view.is_symlink() or not projection.staged_view.is_dir():
        raise InjectorError(f"node {projection.node_name!r} projected PKI view is unavailable")
    if not _matching_bind(node, projection):
        raise InjectorError(f"node {projection.node_name!r} bind does not match its PKI projection")
    view = projection.staged_view.resolve()
    for artifact in projection.files():
        _validate_file(projection.node_name, artifact, view)


def _validate_file(node_name: str, artifact: ProjectedFile, view: Path) -> None:
    if artifact.host_path.is_symlink() or not artifact.host_path.is_file():
        raise InjectorError(
            f"node {node_name!r} projected PKI file is unavailable: {artifact.container_path}"
        )
    try:
        artifact.host_path.resolve(strict=True).relative_to(view)
    except (OSError, ValueError) as error:
        raise InjectorError(
            f"node {node_name!r} projected PKI file escapes its staged view: "
            f"{artifact.container_path}"
        ) from error


def _matching_bind(node: dict[str, Any], projection: NodePkiProjection) -> bool:
    binds = node.get("binds", [])
    if not isinstance(binds, list):
        raise InjectorError(f"node {projection.node_name!r} binds must be a list")
    source = str(projection.staged_view)
    target = str(projection.mount_target)
    for bind in binds:
        if isinstance(bind, str):
            parts = bind.rsplit(":", 2)
            if len(parts) == 3 and parts == [source, target, "ro"]:
                return True
        elif isinstance(bind, dict):
            mode = bind.get("mode", bind.get("options"))
            if bind.get("source") == source and bind.get("target") == target and mode == "ro":
                return True
    return False


def _environment_values(projection: NodePkiProjection) -> dict[str, str]:
    ca_entries: list[str] = []
    ca_refnames: set[str] = set()
    ca_fingerprints: set[str] = set()
    for authority in projection.trusted_authorities:
        if authority.fingerprint_sha256 not in ca_fingerprints:
            ca_fingerprints.add(authority.fingerprint_sha256)
            refname = _authority_refname(authority.name, authority.variant)
            _claim_refname(CA_CERTIFICATES, refname, ca_refnames)
            ca_entries.append(f"{refname}:{authority.certificate.container_path}")
    local_entries: list[str] = []
    local_refnames: set[str] = set()
    local_fingerprints: set[str] = set()
    for local_authority in projection.requested_authorities:
        if local_authority.fingerprint_sha256 not in local_fingerprints:
            local_fingerprints.add(local_authority.fingerprint_sha256)
            refname = _authority_refname(local_authority.name, local_authority.variant)
            _claim_refname(LOCAL_CERTIFICATES, refname, local_refnames)
            fields = [refname]
            if local_authority.private_key is not None:
                fields.append(str(local_authority.private_key.container_path))
            fields.append(str(local_authority.certificate.container_path))
            local_entries.append(":".join(fields))
    for identity in projection.issued_identities:
        if identity.fingerprint_sha256 not in local_fingerprints:
            local_fingerprints.add(identity.fingerprint_sha256)
            refname = identity.request_name.split("/", 1)[1]
            _claim_refname(LOCAL_CERTIFICATES, refname, local_refnames)
            local_entries.append(
                f"{refname}:{identity.private_key.container_path}:"
                f"{identity.certificate.container_path}"
            )

    generated: dict[str, str] = {}
    if ca_entries:
        generated[CA_CERTIFICATES] = ";".join(ca_entries)
    if local_entries:
        generated[LOCAL_CERTIFICATES] = ";".join(local_entries)
    return generated


def _authority_refname(name: str, variant: str) -> str:
    return name if variant == "default" else f"{name}-{variant}"


def _claim_refname(variable: str, refname: str, claimed: set[str]) -> None:
    if not refname or any(character in refname for character in (":", ";")):
        raise InjectorError(f"{variable} refname {refname!r} is invalid")
    if refname in claimed:
        raise InjectorError(f"{variable} contains duplicate refname {refname!r}")
    claimed.add(refname)
