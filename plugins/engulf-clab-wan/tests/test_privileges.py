from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from engulf_clab_wan import dhcp_server, networks, process
from engulf_clab_wan.errors import WanError


def test_unmarked_labs_do_not_authenticate(monkeypatch: pytest.MonkeyPatch) -> None:
    authenticate = Mock()
    monkeypatch.setattr(networks, "require_root_access", authenticate)
    networks.require_root([])
    authenticate.assert_not_called()
    networks.require_root(["wan"])
    authenticate.assert_called_once_with()


def test_missing_sudo_reports_privilege_failure_before_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        networks, "require_root_access", Mock(side_effect=FileNotFoundError("sudo"))
    )
    with pytest.raises(WanError, match="requires sudo access"):
        networks.require_root(["wan"])


def test_privileged_network_commands_and_rule_queries_use_sudo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def elevate(argv: list[str]) -> list[str]:
        return ["sudo", "--", *argv]

    run = Mock(return_value=subprocess.CompletedProcess([], 0))
    monkeypatch.setattr(networks, "root_command", elevate)
    monkeypatch.setattr(process, "root_command", elevate)
    monkeypatch.setattr(subprocess, "run", run)
    process.run(["ip", "link", "set", "wan", "up"])
    assert run.call_args.args[0] == ["sudo", "--", "ip", "link", "set", "wan", "up"]
    networks.run_quiet(["iptables", "-C", "FORWARD", "-j", "ACCEPT"])
    assert run.call_args.args[0][:4] == ["sudo", "--", "iptables", "-C"]
    networks.interface_exists("wan")
    assert run.call_args.args[0] == ["ip", "link", "show", "dev", "wan"]


@pytest.mark.parametrize("root", [False, True])
def test_dhcp_start_authenticates_before_detaching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, root: bool
) -> None:
    state = Mock()
    state.path.side_effect = lambda filename: tmp_path / filename
    state.exists.side_effect = [False, False, True]
    state.read_text.return_value = '{"pid": 321}'
    bridge = SimpleNamespace(
        name="wan",
        subnet="198.19.0.0/24",
        gateway="198.19.0.1",
        pool_start="198.19.0.100",
        pool_end="198.19.0.200",
        dns="192.0.2.53",
        lease_time=43200,
    )
    elevate = Mock(return_value=["sudo", "-n", "-b", "--", "python"])
    spawn = Mock(return_value=Mock(poll=Mock(return_value=0)))
    monkeypatch.setattr(networks, "root_command", elevate)
    monkeypatch.setattr(networks.subprocess, "Popen", spawn)
    monkeypatch.setattr(networks, "process_alive", lambda _pid: True)
    monkeypatch.setattr(networks.time, "sleep", Mock())
    monkeypatch.setattr(networks, "info", Mock())
    monkeypatch.setattr(os, "geteuid", lambda: 0 if root else 1000)
    networks.start_dhcp_server(state, bridge)
    assert spawn.call_args.kwargs["start_new_session"] is root
    assert spawn.call_args.kwargs["stdin"] == subprocess.DEVNULL
    assert elevate.call_args.kwargs == {"non_interactive": True, "background": True}
    assert elevate.call_args.args[0] == [
        sys.executable,
        "-I",
        "-m",
        "engulf_clab_wan.dhcp_server",
        str(tmp_path / "wan.dhcp.json"),
        str(tmp_path / "wan.dhcp.pid"),
        "--uid",
        str(os.getuid()),
        "--gid",
        str(os.getgid()),
    ]


@pytest.mark.parametrize("record", ["0", "-1", '{"pid": -5}', "true", "1.5", "{}"])
def test_invalid_pid_never_reaches_signal_or_sudo(
    monkeypatch: pytest.MonkeyPatch, record: str
) -> None:
    state = Mock()
    state.read_text.return_value = record
    kill = Mock()
    run = Mock()
    monkeypatch.setattr(networks.os, "kill", kill)
    monkeypatch.setattr(networks, "run", run)
    networks.stop_pid_file(state, "wan.dhcp.pid")
    kill.assert_not_called()
    run.assert_not_called()
    state.delete.assert_called_once_with("wan.dhcp.pid")


@pytest.mark.parametrize("managed", [True, False])
def test_legacy_root_helper_requires_identity_check_before_sudo_kill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, managed: bool
) -> None:
    state = Mock()
    state.read_text.return_value = '{"pid": 123}'
    state.path.return_value = tmp_path / "wan.dhcp.json"
    verify = Mock(return_value=managed)
    run = Mock()
    monkeypatch.setattr(networks, "managed_dhcp_process", verify)
    monkeypatch.setattr(
        networks, "process_alive", Mock(side_effect=[True, False, False])
    )
    monkeypatch.setattr(networks.os, "kill", Mock(side_effect=PermissionError))
    monkeypatch.setattr(networks, "run", run)
    monkeypatch.setattr(networks, "info", Mock())
    if managed:
        networks.stop_pid_file(state, "wan.dhcp.pid")
        run.assert_called_once_with(["kill", "-TERM", "123"])
        state.delete.assert_called_once_with("wan.dhcp.pid", missing_ok=True)
    else:
        with pytest.raises(WanError, match="does not match"):
            networks.stop_pid_file(state, "wan.dhcp.pid")
        run.assert_not_called()
        state.delete.assert_not_called()
    verify.assert_called_once_with(123, tmp_path / "wan.dhcp.json")


def test_dhcp_drops_privilege_before_pid_and_lease_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sequence: list[object] = []
    config = SimpleNamespace(interface="wan")
    sock = Mock()
    sock.bind.side_effect = lambda address: sequence.append(("bind", address))
    socket_context = Mock()
    socket_context.__enter__ = Mock(return_value=sock)
    socket_context.__exit__ = Mock(return_value=None)
    monkeypatch.setattr(dhcp_server.socket, "socket", Mock(return_value=socket_context))
    monkeypatch.setattr(dhcp_server, "config_from_file", lambda _path: config)
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        os, "setgroups", lambda groups: sequence.append(("groups", groups))
    )
    monkeypatch.setattr(os, "setgid", lambda gid: sequence.append(("gid", gid)))
    monkeypatch.setattr(os, "setuid", lambda uid: sequence.append(("uid", uid)))
    write = Path.write_text

    def write_pid(path: Path, text: str, **kwargs: object) -> int:
        sequence.append("pid")
        return write(path, text, **kwargs)

    monkeypatch.setattr(Path, "write_text", write_pid)
    monkeypatch.setattr(dhcp_server, "serve", lambda *_args: sequence.append("serve"))
    pid = tmp_path / "wan.pid"
    assert (
        dhcp_server.main(["config.json", str(pid), "--uid", "1000", "--gid", "1001"])
        == 0
    )
    assert sequence == [
        ("bind", ("wan", 0)),
        ("groups", []),
        ("gid", 1001),
        ("uid", 1000),
        "pid",
        "serve",
    ]
    assert json.loads(pid.read_text())["pid"] == os.getpid()


def test_failed_socket_creation_leaves_no_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        dhcp_server, "config_from_file", lambda _path: SimpleNamespace(interface="wan")
    )
    monkeypatch.setattr(
        dhcp_server.socket, "socket", Mock(side_effect=PermissionError("raw socket"))
    )
    pid = tmp_path / "wan.pid"
    with pytest.raises(PermissionError, match="raw socket"):
        dhcp_server.main(["config.json", str(pid)])
    assert not pid.exists()
