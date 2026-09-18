from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import engulf_host_exec as host


@pytest.fixture
def local_docker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for name in (
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_CONFIG",
        "SSH_AUTH_SOCK",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path))
    monkeypatch.setattr(host.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(host, "_executable", lambda command: "/usr/bin/" + command)
    real_stat = os.stat

    def socket_stat(path: object, *args: object, **kwargs: object) -> object:
        if path == "/var/run/docker.sock":
            return SimpleNamespace(st_mode=stat.S_IFSOCK)
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(host.os, "stat", socket_stat)
    monkeypatch.setattr(host.os, "access", lambda *_args: False)
    return tmp_path


def test_inaccessible_socket_uses_sudo_and_callers_config(local_docker: Path) -> None:
    assert host.docker_command(["docker", "image", "inspect", "lab:1"]) == [
        "/usr/bin/sudo",
        "--preserve-env=DOCKER_CONFIG",
        "--",
        "/usr/bin/docker",
        "--config",
        str(local_docker),
        "image",
        "inspect",
        "lab:1",
    ]


@pytest.mark.parametrize("root,accessible", [(True, False), (False, True)])
def test_sudoless_docker_runs_directly(
    local_docker: Path,
    monkeypatch: pytest.MonkeyPatch,
    root: bool,
    accessible: bool,
) -> None:
    monkeypatch.setattr(host.os, "geteuid", lambda: 0 if root else 1000)
    monkeypatch.setattr(host.os, "access", lambda *_args: accessible)
    command = ("docker", "image", "rm", "lab:1")
    assert host.docker_command(command) == command


@pytest.mark.parametrize(
    "endpoint", ["tcp://daemon.test:2376", "ssh://lab.test", "unix:///missing.sock"]
)
def test_no_escalation_for_remote_or_missing_daemon(
    local_docker: Path,
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
) -> None:
    monkeypatch.setenv("DOCKER_HOST", endpoint)
    assert not host.docker_needs_sudo()


def test_current_context_and_explicit_context_override_default_daemon(
    local_docker: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (local_docker / "config.json").write_text(json.dumps({"currentContext": "remote"}))
    metadata = local_docker / "contexts" / "meta" / "context-hash"
    metadata.mkdir(parents=True)
    (metadata / "meta.json").write_text(
        json.dumps(
            {
                "Name": "remote",
                "Endpoints": {"docker": {"Host": "ssh://lab.test"}},
            }
        )
    )
    assert not host.docker_needs_sudo()
    monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
    assert host.docker_needs_sudo()
    monkeypatch.setenv("DOCKER_CONTEXT", "remote")
    assert not host.docker_needs_sudo()
    monkeypatch.setenv("DOCKER_CONTEXT", "unknown")
    assert not host.docker_needs_sudo()


def test_root_command_resolves_child_before_sudo_resets_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(host.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(
        host.shutil,
        "which",
        lambda name: {
            "sudo": "/usr/bin/sudo",
            "ip": "/sbin/ip",
            "/venv/bin/python": "/venv/bin/python",
        }.get(name),
    )
    assert host.root_command(["ip", "link", "set", "wan", "up"]) == [
        "/usr/bin/sudo",
        "--",
        "/sbin/ip",
        "link",
        "set",
        "wan",
        "up",
    ]
    assert host.root_command(
        ["/venv/bin/python", "-m", "helper"], non_interactive=True, background=True
    ) == [
        "/usr/bin/sudo",
        "-n",
        "-b",
        "--",
        "/venv/bin/python",
        "-m",
        "helper",
    ]
    monkeypatch.setattr(host.shutil, "which", lambda _name: None)
    with pytest.raises(FileNotFoundError, match="sudo"):
        host.root_command(["ip", "link", "set", "wan", "up"])


def test_make_shim_is_scoped_to_child_and_cleaned_on_failure(
    local_docker: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authenticate = Mock()
    monkeypatch.setattr(host, "require_root_access", authenticate)
    path = os.environ.get("PATH")
    with (
        pytest.raises(RuntimeError, match="build failed"),
        host.docker_environment() as environment,
    ):
        assert environment is not None
        shim = Path(environment["PATH"].split(os.pathsep)[0]) / "docker"
        assert "/usr/bin/sudo" in shim.read_text()
        assert '"$@"' in shim.read_text()
        assert os.environ.get("PATH") == path
        raise RuntimeError("build failed")
    authenticate.assert_called_once_with()
    assert not shim.exists()
    assert os.environ.get("PATH") == path
