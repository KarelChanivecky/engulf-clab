from __future__ import annotations

import ipaddress
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .errors import WanError
from .logging import info
from .process import run

MARKER_LABEL = "FCLAB_DHCP_WAN"
DEFAULT_SUBNET = "198.19.0.0/24"
DEFAULT_GATEWAY = "198.19.0.1"
DEFAULT_POOL_START = "198.19.0.100"
DEFAULT_POOL_END = "198.19.0.200"
DEFAULT_DNS = "1.1.1.1"
DEFAULT_LEASE_TIME = 12 * 60 * 60
RUNTIME_DIR_NAME = ".forticlab"


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


def runtime_dir(topology_path: Path) -> Path:
    return topology_path.resolve().parent / RUNTIME_DIR_NAME


def labels_include_marker(labels: Any) -> bool:
    if isinstance(labels, dict):
        for key, value in labels.items():
            if str(key) == MARKER_LABEL:
                return str(value).lower() not in ("0", "false", "no", "off")
            if str(value) == MARKER_LABEL:
                return True
    if isinstance(labels, list):
        return any(str(item) == MARKER_LABEL for item in labels)
    if isinstance(labels, str):
        return labels == MARKER_LABEL
    return False


def label_value(labels: Any, key: str, default: str) -> str:
    if isinstance(labels, dict) and key in labels:
        return str(labels[key])
    return default


def parse_bridge(name: str, node_data: dict[str, Any]) -> DhcpWanBridge:
    labels = node_data.get("labels", {})
    subnet = ipaddress.IPv4Network(
        label_value(labels, "FCLAB_DHCP_SUBNET", DEFAULT_SUBNET),
        strict=False,
    )
    gateway = ipaddress.IPv4Address(
        label_value(labels, "FCLAB_DHCP_GATEWAY", DEFAULT_GATEWAY)
    )
    pool_start = ipaddress.IPv4Address(
        label_value(labels, "FCLAB_DHCP_POOL_START", DEFAULT_POOL_START)
    )
    pool_end = ipaddress.IPv4Address(
        label_value(labels, "FCLAB_DHCP_POOL_END", DEFAULT_POOL_END)
    )
    dns = ipaddress.IPv4Address(label_value(labels, "FCLAB_DHCP_DNS", DEFAULT_DNS))
    lease_time = int(label_value(labels, "FCLAB_DHCP_LEASE_TIME", str(DEFAULT_LEASE_TIME)))

    if gateway not in subnet:
        raise WanError(f"{name}: FCLAB_DHCP_GATEWAY must be inside FCLAB_DHCP_SUBNET")
    if pool_start not in subnet or pool_end not in subnet:
        raise WanError(f"{name}: DHCP pool must be inside FCLAB_DHCP_SUBNET")
    if pool_start > pool_end:
        raise WanError(
            f"{name}: FCLAB_DHCP_POOL_START must not exceed FCLAB_DHCP_POOL_END"
        )
    if lease_time <= 0:
        raise WanError(f"{name}: FCLAB_DHCP_LEASE_TIME must be positive")

    return DhcpWanBridge(
        name=name,
        subnet=subnet,
        gateway=gateway,
        pool_start=pool_start,
        pool_end=pool_end,
        dns=dns,
        lease_time=lease_time,
    )


def dhcp_wan_bridges(topology_data: dict[str, Any]) -> list[DhcpWanBridge]:
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
        if labels_include_marker(node_data.get("labels")):
            bridges.append(parse_bridge(str(name), node_data))
    return bridges


def require_root(bridges: list[DhcpWanBridge]) -> None:
    if bridges and hasattr(os, "geteuid") and os.geteuid() != 0:
        raise WanError(f"{MARKER_LABEL} bridge setup requires root")


def interface_exists(name: str) -> bool:
    result = subprocess.run(
        ["ip", "link", "show", "dev", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


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
        argv,
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


def detect_uplink_interface() -> str:
    configured = os.environ.get("FCLAB_UPLINK_IF")
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
    raise WanError("could not detect host uplink interface; set FCLAB_UPLINK_IF")


def config_path(run_dir: Path, bridge: DhcpWanBridge) -> Path:
    return run_dir / f"{bridge.name}.dhcp.json"


def pid_path(run_dir: Path, bridge_name: str) -> Path:
    return run_dir / f"{bridge_name}.dhcp.pid"


def lease_path(run_dir: Path, bridge: DhcpWanBridge) -> Path:
    return run_dir / f"{bridge.name}.leases.json"


def metadata_path(run_dir: Path) -> Path:
    return run_dir / "dhcp-wan.json"


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def stop_pid_file(path: Path) -> None:
    if not path.exists():
        return
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        path.unlink()
        return
    if process_alive(pid):
        info(f"stopping DHCP server pid={pid}")
        os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            if not process_alive(pid):
                break
            time.sleep(0.1)
    path.unlink(missing_ok=True)


def start_dhcp_server(run_dir: Path, bridge: DhcpWanBridge) -> None:
    stop_pid_file(pid_path(run_dir, bridge.name))
    config = {
        "interface": bridge.name,
        "subnet": str(bridge.subnet),
        "gateway": str(bridge.gateway),
        "pool_start": str(bridge.pool_start),
        "pool_end": str(bridge.pool_end),
        "dns": str(bridge.dns),
        "lease_time": bridge.lease_time,
        "lease_file": str(lease_path(run_dir, bridge)),
    }
    config_file = config_path(run_dir, bridge)
    pid_file = pid_path(run_dir, bridge.name)
    log_file = run_dir / f"{bridge.name}.dhcp.log"
    config_file.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")

    with log_file.open("ab") as log:
        info(
            f"starting DHCP server bridge={bridge.name} "
            f"pool={bridge.pool_start}-{bridge.pool_end} dns={bridge.dns}"
        )
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "engulf_clab_wan.dhcp_server",
                str(config_file),
                str(pid_file),
            ],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )

    for _ in range(20):
        if process.poll() is not None:
            break
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text(encoding="utf-8").strip())
            except ValueError:
                pid = 0
            if pid and process_alive(pid):
                info(f"DHCP server running bridge={bridge.name} pid={pid}")
                return
        time.sleep(0.1)

    output = ""
    if log_file.exists():
        output = log_file.read_text(errors="replace").strip()
    detail = f"; log: {output}" if output else ""
    raise WanError(f"DHCP server failed to start for bridge {bridge.name}{detail}")


def bridge_metadata(bridge: DhcpWanBridge, created: bool, uplink: str) -> dict[str, Any]:
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
            "uplink": uplink,
        }
    )
    return data


def save_metadata(run_dir: Path, entries: list[dict[str, Any]]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    metadata_path(run_dir).write_text(
        json.dumps(entries, indent=2, sort_keys=True) + "\n"
    )


def load_metadata(run_dir: Path) -> list[dict[str, Any]]:
    path = metadata_path(run_dir)
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, list) else []


def setup_bridge(bridge: DhcpWanBridge, run_dir: Path, uplink: str) -> dict[str, Any]:
    created = not interface_exists(bridge.name)
    if created:
        info(f"creating Linux bridge {bridge.name}")
        run(["ip", "link", "add", bridge.name, "type", "bridge"])
    else:
        info(f"using existing Linux bridge {bridge.name}")

    info(f"configuring {bridge.name} gateway {bridge.gateway_with_prefix}")
    run(["ip", "addr", "replace", bridge.gateway_with_prefix, "dev", bridge.name])
    run(["ip", "link", "set", bridge.name, "up"])
    info("enabling IPv4 forwarding")
    run(["sysctl", "-w", "net.ipv4.ip_forward=1"])

    subnet = str(bridge.subnet)
    iptables_add(["FORWARD", "-i", bridge.name, "-o", uplink, "-s", subnet, "-j", "ACCEPT"])
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
            "-j",
            "ACCEPT",
        ]
    )
    iptables_nat_add(["POSTROUTING", "-s", subnet, "-o", uplink, "-j", "MASQUERADE"])
    start_dhcp_server(run_dir, bridge)
    return bridge_metadata(bridge, created, uplink)


def setup_dhcp_wan_bridges(topology_path: Path, topology_data: dict[str, Any]) -> None:
    bridges = dhcp_wan_bridges(topology_data)
    require_root(bridges)
    if not bridges:
        info("no FCLAB_DHCP_WAN bridges found")
        return

    info(f"found {len(bridges)} FCLAB_DHCP_WAN bridge(s)")
    require_commands(["ip", "iptables", "sysctl", "sh"])

    run_dir = runtime_dir(topology_path)
    run_dir.mkdir(parents=True, exist_ok=True)
    info(f"using runtime directory {run_dir}")
    uplink = detect_uplink_interface()
    entries: list[dict[str, Any]] = []
    for bridge in bridges:
        entries.append(setup_bridge(bridge, run_dir, uplink))
        save_metadata(run_dir, entries)


def cleanup_entry(run_dir: Path, entry: dict[str, Any]) -> None:
    name = str(entry["name"])
    subnet = str(entry["subnet"])
    uplink = str(entry["uplink"])

    stop_pid_file(pid_path(run_dir, name))
    iptables_nat_delete_all(["POSTROUTING", "-s", subnet, "-o", uplink, "-j", "MASQUERADE"])
    iptables_delete_all(["FORWARD", "-i", name, "-o", uplink, "-s", subnet, "-j", "ACCEPT"])
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
            "-j",
            "ACCEPT",
        ]
    )
    if bool(entry.get("created")) and interface_exists(name):
        info(f"deleting Linux bridge {name}")
        run(["ip", "link", "delete", name])
    elif interface_exists(name):
        info(f"leaving pre-existing Linux bridge {name}")


def cleanup_dhcp_wan_bridges(topology_path: Path) -> None:
    run_dir = runtime_dir(topology_path)
    entries = load_metadata(run_dir)
    require_root(
        [
            DhcpWanBridge(
                name=str(entry["name"]),
                subnet=ipaddress.IPv4Network(str(entry["subnet"]), strict=False),
                gateway=ipaddress.IPv4Address(str(entry["gateway"])),
                pool_start=ipaddress.IPv4Address(str(entry["pool_start"])),
                pool_end=ipaddress.IPv4Address(str(entry["pool_end"])),
                dns=ipaddress.IPv4Address(str(entry["dns"])),
                lease_time=int(entry.get("lease_time", DEFAULT_LEASE_TIME)),
            )
            for entry in entries
        ]
    )
    if not entries:
        info("no forticlab DHCP WAN runtime metadata found")
        return

    require_commands(["ip", "iptables", "sh"])
    info(f"cleaning up {len(entries)} FCLAB_DHCP_WAN bridge(s)")
    for entry in entries:
        cleanup_entry(run_dir, entry)
    metadata_path(run_dir).unlink(missing_ok=True)
