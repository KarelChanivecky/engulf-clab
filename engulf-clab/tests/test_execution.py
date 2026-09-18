from __future__ import annotations

import grp
import os
import stat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from engulf_executable_wrapper import ExecutableWrapperGoal
from engulf_executable_wrapper_api import OutcomeKind

from engulf_clab import execution


@pytest.fixture
def binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "containerlab"
    target.write_text("#!/bin/sh\nexit 0\n")
    target.chmod(0o755)
    monkeypatch.setattr(execution.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(execution, "docker_needs_sudo", lambda: False)
    return target


@pytest.mark.parametrize(
    "args",
    [
        ("deploy", "-t", "lab.clab.yml"),
        ("dep",),
        ("destroy", "--all"),
        ("des",),
        ("redeploy",),
        ("rdep",),
        ("events",),
        ("inspect", "interfaces"),
        ("version", "upgrade"),
        ("generate", "--deploy"),
        ("tools", "veth", "create"),
        ("tools", "sshx", "attach"),
        ("tools", "api-server", "start"),
        ("--runtime", "podman", "inspect"),
        ("-rpodman", "inspect"),
        ("--vars", "vars.yml", "deploy"),
        ("--log-level", "debug", "--topo", "lab.clab.yml", "deploy"),
    ],
)
def test_privileged_containerlab_calls_use_sudo(
    binary: Path, args: tuple[str, ...]
) -> None:
    assert execution.needs_sudo(binary, args)


@pytest.mark.parametrize(
    "args",
    [
        (),
        ("--help",),
        ("deploy", "--help"),
        ("destroy", "-h"),
        ("help", "deploy"),
        ("version",),
        ("version", "check"),
        ("completion", "bash"),
        ("__complete", "deploy"),
        ("generate",),
        ("generate", "--deploy=false"),
        ("tools", "veth"),
        ("tools", "cert", "create"),
        ("--name", "deploy", "version"),
    ],
)
def test_help_version_and_generation_stay_unprivileged(
    binary: Path, args: tuple[str, ...]
) -> None:
    assert not execution.needs_sudo(binary, args)


def test_suid_requires_root_owner_admin_group_and_suid_mount(
    binary: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        Path, "stat", lambda *_args: SimpleNamespace(st_uid=0, st_mode=stat.S_ISUID)
    )
    monkeypatch.setattr(
        execution.os, "statvfs", lambda _path: SimpleNamespace(f_flag=0)
    )
    monkeypatch.setattr(
        grp, "getgrnam", lambda _name: grp.struct_group(("clab_admins", "x", 77, []))
    )
    monkeypatch.setattr(execution.os, "getgroups", lambda: [77])
    assert not execution.needs_sudo(binary, ("deploy",))
    monkeypatch.setattr(execution.os, "getgroups", list)
    monkeypatch.setattr(execution.os, "getgid", lambda: 1000)
    assert execution.needs_sudo(binary, ("deploy",))
    monkeypatch.setattr(execution.os, "getgroups", lambda: [77])
    monkeypatch.setattr(
        execution.os, "statvfs", lambda _path: SimpleNamespace(f_flag=os.ST_NOSUID)
    )
    assert execution.needs_sudo(binary, ("deploy",))


def test_docker_inspection_escalates_when_socket_requires_it(
    binary: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(execution, "docker_needs_sudo", lambda: True)
    assert execution.needs_sudo(binary, ("inspect",))
    assert not execution.needs_sudo(binary, ("version",))


def test_suid_deploy_handles_its_own_docker_privileges(
    binary: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(execution, "docker_needs_sudo", lambda: True)
    monkeypatch.setattr(execution, "_sudoless", lambda _binary: True)
    assert not execution.needs_sudo(binary, ("deploy",))


def test_already_root_needs_no_sudo(
    binary: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(execution.os, "geteuid", lambda: 0)
    assert not execution.needs_sudo(binary, ("deploy",))


def test_privileged_execution_preserves_arguments_outcome_and_environment(
    binary: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    argv = ("deploy", "-t", "/labs/a space/lab.yml")
    before = dict(os.environ)
    root_command = Mock(return_value=["/usr/bin/sudo", "--", str(binary), *argv])
    monkeypatch.setattr(execution, "root_command", root_command)
    expected = (object(), 1.5)
    execute = Mock(return_value=expected)
    monkeypatch.setattr(ExecutableWrapperGoal, "_execute", execute)
    goal = execution.ContainerlabGoal(str(binary))
    api = Mock()
    assert goal._execute(argv, api) == expected
    execute.assert_called_once_with(("--", str(binary), *argv), api)
    assert root_command.call_args.args[0] == (str(binary), *argv)
    assert os.environ == before
    assert goal.executable == str(binary)


def test_missing_sudo_is_a_spawn_failure_without_running_child(
    binary: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = dict(os.environ)
    monkeypatch.setattr(
        execution, "root_command", Mock(side_effect=FileNotFoundError("sudo"))
    )
    execute = Mock()
    monkeypatch.setattr(ExecutableWrapperGoal, "_execute", execute)
    outcome, _ = execution.ContainerlabGoal(str(binary))._execute(("deploy",), Mock())
    assert outcome.kind is OutcomeKind.SPAWN_FAILED
    assert outcome.exit_code == 127
    assert not outcome.process_started
    execute.assert_not_called()
    assert os.environ == before
