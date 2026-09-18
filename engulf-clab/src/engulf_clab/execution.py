"""Containerlab child privilege selection; the Engulf application stays unprivileged."""

from __future__ import annotations

import os
import stat
import time
from pathlib import Path

from engulf_api import GoalAPI
from engulf_executable_wrapper import ExecutableWrapperGoal
from engulf_executable_wrapper_api import CallOutcome, OutcomeKind
from engulf_host_exec import docker_needs_sudo, root_command

_GLOBAL_VALUES = frozenset(
    {
        "--topo",
        "--topology",
        "-t",
        "--name",
        "--vars",
        "--runtime",
        "-r",
        "--timeout",
        "--log-level",
    }
)
_ROOT_COMMANDS = frozenset(
    {"deploy", "dep", "redeploy", "rdep", "destroy", "des", "events", "ev"}
)
_DOCKER_COMMANDS = _ROOT_COMMANDS | {"inspect", "ins", "i", "save", "exec", "graph"}


def _command(arguments: tuple[str, ...]) -> tuple[str, ...]:
    """Skip global options and their values without mistaking a value for a verb."""
    index = 0
    while index < len(arguments):
        word = arguments[index]
        if word == "--":
            return ()
        if not word.startswith("-"):
            return arguments[index:]
        index += 2 if word in _GLOBAL_VALUES else 1
    return ()


def _sudoless(binary: Path) -> bool:
    import grp

    metadata = binary.stat()
    if metadata.st_uid != 0 or not metadata.st_mode & stat.S_ISUID:
        return False
    if os.statvfs(binary).f_flag & os.ST_NOSUID:
        return False
    try:
        group = grp.getgrnam("clab_admins")
    except KeyError:
        # Containerlab permits SUID execution when the group does not exist.
        return True
    return group.gr_gid in {*os.getgroups(), os.getgid()}


def needs_sudo(binary: Path, arguments: tuple[str, ...]) -> bool:
    if os.name != "posix" or os.geteuid() == 0:
        return False
    before_separator = (
        arguments[: arguments.index("--")] if "--" in arguments else arguments
    )
    if "--help" in before_separator or "-h" in before_separator:
        return False
    command = _command(arguments)
    if not command or command[0] in {
        "help",
        "completion",
        "__complete",
        "__completeNoDesc",
    }:
        return False
    verb = command[0]
    subcommand = _command(command[1:])
    subverb = subcommand[0] if subcommand else None
    action = _command(subcommand[1:])
    runtime = os.environ.get("CLAB_RUNTIME", "docker")
    for index, word in enumerate(before_separator):
        if word in {"--runtime", "-r"} and index + 1 < len(before_separator):
            runtime = before_separator[index + 1]
        elif word.startswith("--runtime="):
            runtime = word.partition("=")[2]
        elif word.startswith("-r") and len(word) > 2:
            runtime = word[2:].removeprefix("=")
    requires_root = (
        verb in _ROOT_COMMANDS
        or (
            verb in {"inspect", "ins", "i"} and subverb in {"interfaces", "int", "intf"}
        )
        or (verb == "version" and subverb in {"upgrade", "update"})
        or (
            verb in {"generate", "gen"}
            and any(word in {"--deploy", "--deploy=true"} for word in before_separator)
        )
        or (
            verb == "tools"
            and (
                subverb == "disable-tx-offload"
                or (
                    bool(action) and subverb in {"veth", "vxlan", "netem", "api-server"}
                )
                or (
                    action[:1] in {("attach",), ("detach",), ("reattach",)}
                    and subverb in {"sshx", "gotty"}
                )
            )
        )
        or runtime not in {"", "docker"}
    )
    if requires_root:
        return not _sudoless(binary)
    uses_docker = verb in _DOCKER_COMMANDS or (
        verb == "tools" and subverb in {"sshx", "gotty", "snapshot"}
    )
    return uses_docker and docker_needs_sudo()


class ContainerlabGoal(ExecutableWrapperGoal):
    """Retain the wrapper lifecycle and signal handling while elevating its child."""

    def _execute(
        self, args: tuple[str, ...], api: GoalAPI
    ) -> tuple[CallOutcome, float]:
        started = time.monotonic()
        try:
            binary = self._resolve_executable()
            self._reject_direct_recursion(binary)
            if not needs_sudo(Path(binary), args):
                return super()._execute(args, api)
            # Docker config must stay associated with the invoking user after sudo.
            config = os.environ.get("DOCKER_CONFIG")
            os.environ["DOCKER_CONFIG"] = config or str(Path.home() / ".docker")
            try:
                preserved = tuple(
                    key for key in os.environ if key.startswith(("CLAB_", "DOCKER_"))
                )
                command = root_command((binary, *args), preserve_env=preserved)
                api.logger.info("using sudo for Containerlab %s", _command(args)[0])
                return ExecutableWrapperGoal(command[0])._execute(
                    tuple(command[1:]), api
                )
            finally:
                if config is None:
                    os.environ.pop("DOCKER_CONFIG", None)
                else:
                    os.environ["DOCKER_CONFIG"] = config
        except OSError as error:
            api.logger.error("cannot execute %s: %s", self.executable, error)
            return (
                CallOutcome(
                    OutcomeKind.SPAWN_FAILED,
                    127 if isinstance(error, FileNotFoundError) else 126,
                    process_started=False,
                    error=str(error),
                ),
                time.monotonic() - started,
            )
