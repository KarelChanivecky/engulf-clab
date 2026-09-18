from __future__ import annotations

import ipaddress
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from engulf_api import StateStore, WorkspaceState
from engulf_host_exec import require_root_access, root_command

from .errors import WanError
from .logging import info
from .process import run
from .registry import (
    begin_rollback,
    bridge_metadata_for_workspace,
    claim_bridge,
    complete_provisioning,
    complete_release,
    complete_rollback,
    load_registry,
    record_provision_step,
    release_bridge,
    save_registry,
    workspace_bridge_names,
)

DEFAULT_SUBNET = "198.19.0.0/24"
DEFAULT_GATEWAY = "198.19.0.1"
DEFAULT_POOL_START = "198.19.0.100"
DEFAULT_POOL_END = "198.19.0.200"
DEFAULT_DNS = "1.1.1.1"
DEFAULT_LEASE_TIME = 12 * 60 * 60
METADATA_FILENAME = "dhcp-wan.json"
LABEL_PREFIX = "ECLAB"
_WAN_LABEL_SUFFIXES = (
    "DHCP_WAN",
    "DHCP_SUBNET",
    "DHCP_GATEWAY",
    "DHCP_POOL_START",
    "DHCP_POOL_END",
    "DHCP_DNS",
    "DHCP_LEASE_TIME",
)


@dataclass(frozen=True, slots=True)
class WanContract:
    prefix: str

    @property
    def marker_label(self) -> str:
        return self.label("DHCP_WAN")

    @property
    def uplink_environment(self) -> str:
        return self.label("UPLINK_IF")

    @property
    def control_labels(self) -> tuple[str, ...]:
        return tuple(self.label(suffix) for suffix in _WAN_LABEL_SUFFIXES)

    def label(self, suffix: str) -> str:
        return f"{self.prefix}_{suffix}"


def wan_contract() -> WanContract:
    """Return the fixed-prefix WAN contract, shared by every edition.

    The label prefix is a fixed ``ECLAB`` literal rather than derived from
    the active application's product metadata, so labels written for one
    edition remain portable across all of them.
    """
    return WanContract(LABEL_PREFIX)


@dataclass(frozen=True)
class DhcpWanBridge:
    name: str
    subnet: ipaddress.IPv4Network
    gateway: ipaddress.IPv4Address
    pool_start: ipaddress.IPv4Address
    pool_end: ipaddress.IPv4Address
    dns: ipaddress.IPv4Address
    lease_time: int

    @property
    def gateway_with_prefix(self) -> str:
        return f"{self.gateway}/{self.subnet.prefixlen}"


def labels_include_marker(labels: Any, contract: WanContract) -> bool:
    if isinstance(labels, dict):
        for key, value in labels.items():
            if str(key) == contract.marker_label:
                return str(value).lower() not in ("0", "false", "no", "off")
            if str(value) == contract.marker_label:
                return True
    if isinstance(labels, list):
        return any(str(item) == contract.marker_label for item in labels)
    if isinstance(labels, str):
        return labels == contract.marker_label
    return False


def label_value(labels: Any, key: str, default: str) -> str:
    if isinstance(labels, dict) and key in labels:
        return str(labels[key])
    return default


def parse_bridge(
    name: str, node_data: dict[str, Any], contract: WanContract
) -> DhcpWanBridge:
    labels = node_data.get("labels", {})
    subnet = ipaddress.IPv4Network(
        label_value(labels, contract.label("DHCP_SUBNET"), DEFAULT_SUBNET),
        strict=False,
    )
    gateway = ipaddress.IPv4Address(
        label_value(labels, contract.label("DHCP_GATEWAY"), DEFAULT_GATEWAY)
    )
    pool_start = ipaddress.IPv4Address(
        label_value(labels, contract.label("DHCP_POOL_START"), DEFAULT_POOL_START)
    )
    pool_end = ipaddress.IPv4Address(
        label_value(labels, contract.label("DHCP_POOL_END"), DEFAULT_POOL_END)
    )
    dns = ipaddress.IPv4Address(
        label_value(labels, contract.label("DHCP_DNS"), DEFAULT_DNS)
    )
    lease_time = int(
        label_value(labels, contract.label("DHCP_LEASE_TIME"), str(DEFAULT_LEASE_TIME))
    )

    if gateway not in subnet:
        raise WanError(
            f"{name}: {contract.label('DHCP_GATEWAY')} must be inside "
            f"{contract.label('DHCP_SUBNET')}"
        )
    if pool_start not in subnet or pool_end not in subnet:
        raise WanError(
            f"{name}: DHCP pool must be inside {contract.label('DHCP_SUBNET')}"
        )
    if pool_start > pool_end:
        raise WanError(
            f"{name}: {contract.label('DHCP_POOL_START')} must not exceed "
            f"{contract.label('DHCP_POOL_END')}"
        )
    if lease_time <= 0:
        raise WanError(f"{name}: {contract.label('DHCP_LEASE_TIME')} must be positive")

    return DhcpWanBridge(
        name=name,
        subnet=subnet,
        gateway=gateway,
        pool_start=pool_start,
        pool_end=pool_end,
        dns=dns,
        lease_time=lease_time,
    )


def dhcp_wan_bridges(
    topology_data: dict[str, Any], contract: WanContract
) -> list[DhcpWanBridge]:
    topology = topology_data.get("topology")
    if not isinstance(topology, dict):
        return []
    nodes = topology.get("nodes")
    if not isinstance(nodes, dict):
        return []

    bridges: list[DhcpWanBridge] = []
    for name, node_data in nodes.items():
        if not isinstance(node_data, dict):
            continue
        if node_data.get("kind") != "bridge":
            continue
        labels = node_data.get("labels")
        if labels_include_marker(labels, contract):
            bridges.append(parse_bridge(str(name), node_data, contract))
    return bridges


def require_root(bridges: Sequence[object], marker_label: str = "DHCP WAN") -> None:
    if bridges:
        try:
            require_root_access()
        except (OSError, subprocess.CalledProcessError) as error:
            raise WanError(f"{marker_label} bridge setup requires sudo access: {error}") from error


def interface_exists(name: str) -> bool:
    result = subprocess.run(
        ["ip", "link", "show", "dev", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def interface_has_address(name: str, address: str) -> bool:
    result = subprocess.run(
        ["ip", "-4", "-o", "addr", "show", "dev", name],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        text=True,
    )
    return any(address in line.split() for line in result.stdout.splitlines())


def command_exists(name: str) -> bool:
    result = subprocess.run(
        ["sh", "-c", f"command -v {name} >/dev/null 2>&1"],
        check=False,
    )
    return result.returncode == 0


def require_commands(commands: list[str]) -> None:
    for command in commands:
        if not command_exists(command):
            raise WanError(f"missing required command: {command}")


def run_quiet(argv: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        root_command(argv),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def iptables_add(args: list[str]) -> None:
    if run_quiet(["iptables", "-C", *args]).returncode != 0:
        info(f"adding iptables rule: {' '.join(args)}")
        run(["iptables", "-A", *args])
    else:
        info(f"iptables rule already present: {' '.join(args)}")


def iptables_delete_all(args: list[str]) -> None:
    removed = 0
    while run_quiet(["iptables", "-C", *args]).returncode == 0:
        run(["iptables", "-D", *args])
        removed += 1
    if removed:
        info(f"removed {removed} iptables rule(s): {' '.join(args)}")


def iptables_nat_add(args: list[str]) -> None:
    if run_quiet(["iptables", "-t", "nat", "-C", *args]).returncode != 0:
        info(f"adding iptables nat rule: {' '.join(args)}")
        run(["iptables", "-t", "nat", "-A", *args])
    else:
        info(f"iptables nat rule already present: {' '.join(args)}")


def iptables_nat_delete_all(args: list[str]) -> None:
    removed = 0
    while run_quiet(["iptables", "-t", "nat", "-C", *args]).returncode == 0:
        run(["iptables", "-t", "nat", "-D", *args])
        removed += 1
    if removed:
        info(f"removed {removed} iptables nat rule(s): {' '.join(args)}")


def detect_uplink_interface(
    contract: WanContract, environ: Mapping[str, str] | None = None
) -> str:
    current_env = os.environ if environ is None else environ
    configured = current_env.get(contract.uplink_environment)
    if configured:
        info(f"using configured host uplink {configured}")
        return configured

    result = subprocess.run(
        ["ip", "route", "get", "1.1.1.1"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    words = result.stdout.split()
    for index, word in enumerate(words):
        if word == "dev" and index + 1 < len(words):
            uplink = words[index + 1]
            info(f"detected host uplink {uplink}")
            return uplink
    raise WanError(
        f"could not detect host uplink interface; set {contract.uplink_environment}"
    )


def _ip_forward_value() -> str:
    result = subprocess.run(
        ["sysctl", "-n", "net.ipv4.ip_forward"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    value = result.stdout.strip()
    if value not in {"0", "1"}:
        raise WanError(f"unexpected net.ipv4.ip_forward value: {value!r}")
    return value


def ensure_ip_forwarding(state: StateStore) -> None:
    current = _ip_forward_value()
    with state.transaction() as locked:
        registry = load_registry(locked)
        forwarding = registry.get("ip_forward")
        if forwarding is None:
            registry["ip_forward"] = {"original": current}
            save_registry(locked, registry)
        elif not isinstance(forwarding, dict) or forwarding.get("original") not in {
            "0",
            "1",
        }:
            raise WanError("WAN registry has invalid IPv4 forwarding metadata")
    if current != "1":
        info("enabling IPv4 forwarding")
        run(["sysctl", "-w", "net.ipv4.ip_forward=1"])


def restore_ip_forwarding_if_unused(state: StateStore) -> None:
    with state.transaction() as locked:
        registry = load_registry(locked)
        bridges = registry["bridges"]
        assert isinstance(bridges, dict)
        forwarding = registry.get("ip_forward")
        if bridges or forwarding is None:
            return
        if not isinstance(forwarding, dict) or forwarding.get("original") not in {
            "0",
            "1",
        }:
            raise WanError("WAN registry has invalid IPv4 forwarding metadata")
        original = str(forwarding["original"])

    if original != "1" and _ip_forward_value() == "1":
        info(f"restoring IPv4 forwarding to {original}")
        run(["sysctl", "-w", f"net.ipv4.ip_forward={original}"])

    with state.transaction() as locked:
        registry = load_registry(locked)
        bridges = registry["bridges"]
        assert isinstance(bridges, dict)
        if not bridges:
            registry.pop("ip_forward", None)
            save_registry(locked, registry)


def config_filename(bridge: DhcpWanBridge) -> str:
    return f"{bridge.name}.dhcp.json"


def pid_filename(bridge_name: str) -> str:
    return f"{bridge_name}.dhcp.pid"


def lease_filename(bridge: DhcpWanBridge) -> str:
    return f"{bridge.name}.leases.json"


def log_filename(bridge: DhcpWanBridge) -> str:
    return f"{bridge.name}.dhcp.log"


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def managed_dhcp_process(pid: int, config_file: Path) -> bool:
    try:
        command_line = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False
    return (
        b"engulf_clab_wan.dhcp_server" in command_line
        and os.fsencode(config_file) in command_line
    )


def _pid_from_state(state: StateStore, filename: str) -> int:
    content = state.read_text(filename).strip()
    try:
        value: Any = json.loads(content)
    except json.JSONDecodeError:
        value = content
    if isinstance(value, dict):
        value = value.get("pid")
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise WanError(f"invalid DHCP server PID record: {filename}")
    try:
        pid = int(value)
    except (TypeError, ValueError) as error:
        raise WanError(f"invalid DHCP server PID record: {filename}") from error
    if pid <= 0:
        raise WanError(f"invalid DHCP server PID record: {filename}")
    return pid


def stop_pid_file(state: StateStore, filename: str) -> None:
    if not state.exists(filename):
        return
    try:
        pid = _pid_from_state(state, filename)
    except WanError:
        state.delete(filename)
        return
    if process_alive(pid):
        config_name = filename.removesuffix(".dhcp.pid") + ".dhcp.json"
        if not managed_dhcp_process(pid, state.path(config_name)):
            raise WanError(
                f"DHCP server pid={pid} does not match managed configuration"
            )
        info(f"stopping DHCP server pid={pid}")
        try:
            os.kill(pid, signal.SIGTERM)
        except PermissionError:
            # Recover helpers launched as root by older versions, after the same
            # managed PID/configuration check used for user-owned helpers.
            run(["kill", "-TERM", str(pid)])
        for _ in range(20):
            if not process_alive(pid):
                break
            time.sleep(0.1)
        if process_alive(pid):
            raise WanError(f"DHCP server pid={pid} did not stop")
    state.delete(filename, missing_ok=True)


def start_dhcp_server(state: StateStore, bridge: DhcpWanBridge) -> None:
    pid_name = pid_filename(bridge.name)
    stop_pid_file(state, pid_name)
    lease_file = state.path(lease_filename(bridge))
    config = {
        "interface": bridge.name,
        "subnet": str(bridge.subnet),
        "gateway": str(bridge.gateway),
        "pool_start": str(bridge.pool_start),
        "pool_end": str(bridge.pool_end),
        "dns": str(bridge.dns),
        "lease_time": bridge.lease_time,
        "lease_file": str(lease_file),
    }
    config_name = config_filename(bridge)
    state.write_text(config_name, json.dumps(config, indent=2, sort_keys=True) + "\n")
    config_file = state.path(config_name)
    pid_file = state.path(pid_name)
    log_name = log_filename(bridge)
    log_file = state.path(log_name)

    with log_file.open("ab") as log:
        info(
            f"starting DHCP server bridge={bridge.name} "
            f"pool={bridge.pool_start}-{bridge.pool_end} dns={bridge.dns}"
        )
        process = subprocess.Popen(
            root_command(
                [
                    sys.executable,
                    "-I",
                    "-m",
                    "engulf_clab_wan.dhcp_server",
                    str(config_file),
                    str(pid_file),
                    "--uid", str(os.getuid()),
                    "--gid", str(os.getgid()),
                ],
                non_interactive=True,
                background=True,
            ),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            # sudo must authenticate in the caller's session before it detaches;
            # starting a new session here would lose the tty-scoped sudo ticket.
            start_new_session=os.geteuid() == 0,
        )

    for _ in range(20):
        # sudo -b exits successfully before its background child publishes a PID.
        if process.poll() not in (None, 0):
            break
        if state.exists(pid_name):
            try:
                pid = _pid_from_state(state, pid_name)
            except WanError:
                pid = 0
            if pid and process_alive(pid):
                info(f"DHCP server running bridge={bridge.name} pid={pid}")
                return
        time.sleep(0.1)

    output = ""
    if state.exists(log_name):
        output = state.read_text(log_name, errors="replace").strip()
    detail = f"; log: {output}" if output else ""
    raise WanError(f"DHCP server failed to start for bridge {bridge.name}{detail}")


def bridge_metadata(
    bridge: DhcpWanBridge, created: bool, gateway_added: bool, uplink: str
) -> dict[str, Any]:
    data = asdict(bridge)
    data.update(
        {
            "name": bridge.name,
            "subnet": str(bridge.subnet),
            "gateway": str(bridge.gateway),
            "pool_start": str(bridge.pool_start),
            "pool_end": str(bridge.pool_end),
            "dns": str(bridge.dns),
            "created": created,
            "gateway_added": gateway_added,
            "uplink": uplink,
        }
    )
    return data


def bridge_configuration(bridge: DhcpWanBridge, uplink: str) -> dict[str, Any]:
    data = bridge_metadata(bridge, created=False, gateway_added=False, uplink=uplink)
    data.pop("created")
    data.pop("gateway_added")
    return data


def save_metadata(state: StateStore, entries: list[dict[str, Any]]) -> None:
    state.write_text(
        METADATA_FILENAME,
        json.dumps(entries, indent=2, sort_keys=True) + "\n",
    )


def load_metadata(state: StateStore) -> list[dict[str, Any]]:
    if not state.exists(METADATA_FILENAME):
        return []
    data = json.loads(state.read_text(METADATA_FILENAME))
    return data if isinstance(data, list) else []


def setup_bridge(
    bridge: DhcpWanBridge,
    state: StateStore,
    uplink: str,
    record_step: Callable[[str], None],
) -> dict[str, Any]:
    created = not interface_exists(bridge.name)
    if created:
        info(f"creating Linux bridge {bridge.name}")
        run(["ip", "link", "add", bridge.name, "type", "bridge"])
        record_step("bridge-created")
    else:
        info(f"using existing Linux bridge {bridge.name}")

    gateway_added = False
    if not interface_has_address(bridge.name, bridge.gateway_with_prefix):
        info(f"adding {bridge.name} gateway {bridge.gateway_with_prefix}")
        run(["ip", "addr", "add", bridge.gateway_with_prefix, "dev", bridge.name])
        gateway_added = True
        record_step("gateway-added")
    run(["ip", "link", "set", bridge.name, "up"])
    subnet = str(bridge.subnet)
    marker = f"engulf-clab-wan:{bridge.name}"
    iptables_add(
        [
            "FORWARD",
            "-i",
            bridge.name,
            "-o",
            uplink,
            "-s",
            subnet,
            "-m",
            "comment",
            "--comment",
            marker,
            "-j",
            "ACCEPT",
        ]
    )
    record_step("forward-out")
    iptables_add(
        [
            "FORWARD",
            "-i",
            uplink,
            "-o",
            bridge.name,
            "-d",
            subnet,
            "-m",
            "conntrack",
            "--ctstate",
            "RELATED,ESTABLISHED",
            "-m",
            "comment",
            "--comment",
            marker,
            "-j",
            "ACCEPT",
        ]
    )
    record_step("forward-in")
    iptables_nat_add(
        [
            "POSTROUTING",
            "-s",
            subnet,
            "-o",
            uplink,
            "-m",
            "comment",
            "--comment",
            marker,
            "-j",
            "MASQUERADE",
        ]
    )
    record_step("nat")
    start_dhcp_server(state, bridge)
    record_step("dhcp")
    return bridge_metadata(bridge, created, gateway_added, uplink)


def setup_dhcp_wan_bridges(
    topology_data: dict[str, Any],
    workspace: WorkspaceState,
    user_state: StateStore,
    contract: WanContract,
    environ: Mapping[str, str] | None = None,
) -> None:
    bridges = dhcp_wan_bridges(topology_data, contract)
    require_root(bridges, contract.marker_label)
    if not bridges:
        info(f"no {contract.marker_label} bridges found")
        return

    info(f"found {len(bridges)} {contract.marker_label} bridge(s)")
    require_commands(["ip", "iptables", "sysctl", "sh"])

    info(f"using Engulf user registry {user_state.directory}")
    uplink = detect_uplink_interface(contract, environ)
    ensure_ip_forwarding(user_state)
    workspace_name = os.fspath(workspace.root)
    claims: list[str] = []
    for bridge in bridges:
        rollback_metadata = begin_rollback(user_state, bridge.name)
        if rollback_metadata is not None:
            info(f"recovering unfinished WAN bridge provisioning for {bridge.name}")
            cleanup_entry(user_state, rollback_metadata)
            if complete_rollback(user_state, bridge.name):
                restore_ip_forwarding_if_unused(user_state)

        configuration = bridge_configuration(bridge, uplink)
        needs_provisioning, _entry = claim_bridge(
            user_state,
            workspace=workspace_name,
            configuration=configuration,
        )
        if needs_provisioning:

            def record_step(step: str, *, name: str = bridge.name) -> None:
                record_provision_step(user_state, name, step)

            try:
                metadata = setup_bridge(
                    bridge,
                    user_state,
                    uplink,
                    record_step,
                )
                complete_provisioning(user_state, bridge.name, metadata)
            except Exception as error:
                rollback_metadata = begin_rollback(user_state, bridge.name)
                assert rollback_metadata is not None
                try:
                    cleanup_entry(user_state, rollback_metadata)
                    if complete_rollback(user_state, bridge.name):
                        restore_ip_forwarding_if_unused(user_state)
                except Exception as rollback_error:  # noqa: BLE001 - preserve failed rollback state.
                    raise WanError(
                        f"WAN bridge {bridge.name} provisioning failed and rollback failed: "
                        f"{rollback_error}"
                    ) from error
                raise
        claims.append(bridge.name)
        # Record each claim as it is made. A later bridge in this loop may fail,
        # and the workspace metadata is what destroy and preparation unwind use
        # to find the claims that must still be released.
        bridge_metadata_for_workspace(workspace, claims)
    bridge_metadata_for_workspace(workspace, claims)


def cleanup_entry(state: StateStore, entry: dict[str, Any]) -> None:
    name = str(entry["name"])
    subnet = str(entry["subnet"])
    uplink = str(entry["uplink"])
    marker = f"engulf-clab-wan:{name}"

    stop_pid_file(state, pid_filename(name))
    iptables_nat_delete_all(
        [
            "POSTROUTING",
            "-s",
            subnet,
            "-o",
            uplink,
            "-m",
            "comment",
            "--comment",
            marker,
            "-j",
            "MASQUERADE",
        ]
    )
    iptables_delete_all(
        [
            "FORWARD",
            "-i",
            name,
            "-o",
            uplink,
            "-s",
            subnet,
            "-m",
            "comment",
            "--comment",
            marker,
            "-j",
            "ACCEPT",
        ]
    )
    iptables_delete_all(
        [
            "FORWARD",
            "-i",
            uplink,
            "-o",
            name,
            "-d",
            subnet,
            "-m",
            "conntrack",
            "--ctstate",
            "RELATED,ESTABLISHED",
            "-m",
            "comment",
            "--comment",
            marker,
            "-j",
            "ACCEPT",
        ]
    )
    if bool(entry.get("created")) and interface_exists(name):
        info(f"deleting Linux bridge {name}")
        run(["ip", "link", "delete", name])
    elif interface_exists(name):
        if bool(entry.get("gateway_added")):
            info(f"removing plugin-added gateway {entry['gateway']}")
            run(
                [
                    "ip",
                    "addr",
                    "del",
                    f"{entry['gateway']}/{ipaddress.IPv4Network(str(entry['subnet']), strict=False).prefixlen}",
                    "dev",
                    name,
                ]
            )
        info(f"leaving pre-existing Linux bridge {name}")


def release_workspace_bridges(
    names: Sequence[str],
    workspace: WorkspaceState,
    user_state: StateStore,
) -> None:
    """Release the named claims for one workspace, keeping its state store intact.

    Preparation unwind releases only the bridges a failed invocation added, so it
    must not discard workspace state that a previous successful deploy still owns.
    """
    if not names:
        return
    require_root(names)
    require_commands(["ip", "iptables", "sh"])
    info(f"cleaning up {len(names)} DHCP WAN bridge(s) for {workspace.root}")
    failures: list[str] = []
    workspace_name = os.fspath(workspace.root)
    for name in names:
        try:
            entry = release_bridge(user_state, workspace=workspace_name, name=name)
            if entry is not None:
                cleanup_entry(user_state, entry)
                if complete_release(user_state, name):
                    restore_ip_forwarding_if_unused(user_state)
        except Exception as error:  # noqa: BLE001 - every bridge must be attempted.
            failures.append(f"{name}: {error}")
    if failures:
        raise WanError("DHCP WAN bridge cleanup failed: " + "; ".join(failures))


def cleanup_dhcp_wan_bridges(workspace: WorkspaceState, user_state: StateStore) -> None:
    names = workspace_bridge_names(workspace)
    if not names:
        info(f"no DHCP WAN metadata found for workspace {workspace.root}")
        restore_ip_forwarding_if_unused(user_state)
        workspace.destroy()
        return

    release_workspace_bridges(names, workspace, user_state)
    workspace.destroy()
