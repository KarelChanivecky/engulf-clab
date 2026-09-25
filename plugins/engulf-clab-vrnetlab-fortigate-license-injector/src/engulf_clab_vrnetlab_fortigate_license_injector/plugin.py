from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from engulf_api import BeforeGoalAPI, Invocation, InvocationAPI
from engulf_clab_lab_parser import (
    TOPOLOGY_CONTEXT,
    TopologyError,
    TopologySession,
    effective_nodes,
    is_topology_mutation_command,
)
from engulf_clab_license_pool import LICENSE_SELECTION_CONTEXT, LicenseSelection
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
LICENSE_TARGET = "/tftpboot/appliance.lic"


class InjectorError(RuntimeError):
    """Raised when a selected FortiGate license cannot be safely mounted."""


PLUGIN_SCHEMA = (
    PluginSchema(
        "engulf_clab.vrnetlab_fortigate_license_injector",
        package="engulf_clab_vrnetlab_fortigate_license_injector",
    )
    .use_case("Mount a registered-pool license into the FortiGate vrnetlab TFTP startup path.")
    .reject("Use the registered license-pool workflow; do not author a competing target mount.")
    .order(
        LifecycleStage.PREPARE_CALL,
        "Inject the selected lab-local license copy after allocation and before topology writing.",
        after=("engulf_clab.lab_parser", "engulf_clab.license_pool", "engulf_clab.pki"),
        before=("engulf_clab.lab_writer",),
    )
    .route(
        "inject-fortigate-license",
        "USAGE.md",
        "Read registered-license mounting, lifecycle ownership, and troubleshooting.",
    )
    .refer("USAGE.md")
)


class FortigateLicenseInjector(SchemaBackedPlugin):
    plugin_id = "engulf_clab.vrnetlab_fortigate_license_injector"
    schema = PLUGIN_SCHEMA
    priority = 55
    context_reads = frozenset({TOPOLOGY_CONTEXT, LICENSE_SELECTION_CONTEXT}) | SCHEMA_CONTEXTS
    context_writes = SCHEMA_CONTEXTS

    def before_goal(self, invocation: Invocation, api: BeforeGoalAPI) -> None:
        del invocation
        record_plugin_schema(api, PLUGIN_SCHEMA)

    def help(self, api: HelpAPI) -> str:
        del api
        return (
            "  FortiGate license injection     Mounts a registered license-pool selection read-only "
            "for vrnetlab startup"
        )

    def analyze_call(self, event: BeforeCallEvent, api: InvocationAPI) -> CallContribution | None:
        del event, api
        return None

    def prepare_call(self, event: PreparedCallEvent, api: InvocationAPI) -> None:
        if not is_topology_mutation_command(event.wrapper_args):
            return
        selected = api.get_context(LICENSE_SELECTION_CONTEXT)
        if selected is None:
            return
        if not isinstance(selected, Mapping):
            raise InjectorError("invalid license selection context")
        if not selected:
            return

        session = api.require_context(TOPOLOGY_CONTEXT)
        if not isinstance(session, TopologySession):
            raise InjectorError("invalid shared topology session")
        topology = session.materialize()
        topology_block = topology.get("topology", {})
        if not isinstance(topology_block, dict):
            raise InjectorError("topology must be a mapping")
        nodes = topology_block.get("nodes", {})
        if not isinstance(nodes, dict):
            raise InjectorError("topology.nodes must be a mapping")
        try:
            effective = {node.name: node for node in effective_nodes(topology)}
        except TopologyError as error:
            raise InjectorError("could not resolve effective topology nodes") from error

        mutation = session.editor(self.plugin_id)
        for node_name, selection in selected.items():
            if not isinstance(node_name, str) or not isinstance(selection, LicenseSelection):
                raise InjectorError("invalid selected license entry")
            if selection.node != node_name:
                raise InjectorError("selected license node identity does not match its key")
            node = effective.get(node_name)
            if node is None:
                # An image provider can remove build-only nodes after license
                # projection; those files are unused in the deployable topology.
                continue
            if node.data.get("kind") != FORTIGATE_KIND:
                continue
            direct_node = nodes.get(node_name)
            if not isinstance(direct_node, dict):
                raise InjectorError(f"selected FortiGate node {node_name!r} is malformed")
            license_file = _selected_copy(node_name, node.data.get("license"), selection)
            expected_bind = f"{license_file}:{LICENSE_TARGET}:ro"
            already_mounted = _ensure_target_available(
                node_name, node.data.get("binds", ()), expected_bind
            )
            if not already_mounted:
                _append_direct_bind(mutation, node_name, direct_node, expected_bind)


def _selected_copy(node_name: str, value: Any, selection: LicenseSelection) -> Path:
    if not isinstance(value, str) or not value:
        raise InjectorError(f"selected FortiGate node {node_name!r} has no resolved license copy")
    path = Path(value).expanduser()
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise InjectorError(f"selected FortiGate node {node_name!r} license copy is unavailable")
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise InjectorError(
            f"selected FortiGate node {node_name!r} license copy is unavailable"
        ) from error
    if resolved.name != selection.source_name:
        raise InjectorError(f"selected FortiGate node {node_name!r} license copy is inconsistent")
    return resolved


def _ensure_target_available(node_name: str, binds: Any, expected: str) -> bool:
    if not isinstance(binds, (list, tuple)):
        raise InjectorError(f"selected FortiGate node {node_name!r} binds must be a list")
    expected_parts = expected.rsplit(":", 2)
    found = False
    for bind in binds:
        source, target, readonly = _bind_parts(bind)
        if target != LICENSE_TARGET:
            continue
        if [source, target, readonly] != expected_parts:
            raise InjectorError(
                f"selected FortiGate node {node_name!r} has a conflicting bind at {LICENSE_TARGET}"
            )
        found = True
    return found


def _bind_parts(bind: Any) -> tuple[str | None, str | None, str | None]:
    if isinstance(bind, str):
        parts = bind.rsplit(":", 2)
        if len(parts) == 3:
            return parts[0], parts[1], parts[2]
        if len(parts) == 2:
            return parts[0], parts[1], "rw"
        return None, None, None
    if isinstance(bind, Mapping):
        source = bind.get("source")
        target = bind.get("target")
        mode = bind.get("mode", bind.get("options"))
        if isinstance(mode, (list, tuple)):
            mode = ",".join(str(item) for item in mode)
        return (
            source if isinstance(source, str) else None,
            target if isinstance(target, str) else None,
            mode if isinstance(mode, str) else None,
        )
    return None, None, None


def _append_direct_bind(mutation: Any, node_name: str, node: Mapping[str, Any], bind: str) -> None:
    path = ("topology", "nodes", node_name, "binds")
    current = node.get("binds")
    if current is None and "binds" not in node:
        mutation.add(path, [bind])
        return
    if current is None:
        mutation.modify(path, [bind])
        return
    if not isinstance(current, (list, tuple)):
        raise InjectorError(f"selected FortiGate node {node_name!r} binds must be a list")
    if bind not in current:
        # An earlier plugin may have recorded a whole-list binds edit. A
        # list-index add composes with that edit without replacing its value.
        mutation.add((*path, len(current)), bind)


plugin = FortigateLicenseInjector()
