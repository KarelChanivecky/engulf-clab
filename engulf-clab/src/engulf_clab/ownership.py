"""Restore ownership of eclab artifacts created by elevated invocations."""

from __future__ import annotations

import os
import stat
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path

from engulf import (
    StateHomeContext,
    StateHomeResolver,
    WorkspaceContext,
    WorkspaceRootResolver,
)
from engulf_api import Invocation

type ArtifactPathResolver = Callable[
    [str, Invocation], Iterable[str | os.PathLike[str]]
]


def restore_sudo_ownership(path: Path) -> None:
    """Return root-owned files in ``path`` to the user who invoked sudo.

    The traversal is limited to the supplied artifact root, does not follow
    symlinks, and preserves setuid/setgid files and directories.
    """
    if not hasattr(os, "geteuid") or not hasattr(os, "chown") or os.geteuid() != 0:
        return
    try:
        uid = int(os.environ["SUDO_UID"])
    except (KeyError, ValueError):
        return
    if uid <= 0:
        return
    try:
        raw_gid = os.environ.get("SUDO_GID")
        if raw_gid is None:
            import pwd

            gid = pwd.getpwuid(uid).pw_gid
        else:
            gid = int(raw_gid)
    except (ImportError, KeyError, ValueError):
        return

    target = path.expanduser()
    if target.is_symlink() or not target.exists():
        return
    if target.is_dir():
        for directory, child_directories, filenames in os.walk(
            target, topdown=True, followlinks=False
        ):
            current = Path(directory)
            _chown_root_owned(current, uid, gid)
            child_directories[:] = [
                name
                for name in child_directories
                if not (current / name).is_symlink()
            ]
            for name in (*child_directories, *filenames):
                child = current / name
                if not child.is_symlink():
                    _chown_root_owned(child, uid, gid)
    else:
        _chown_root_owned(target, uid, gid)


def restore_sudo_application_artifacts(
    application_id: str,
    arguments: Sequence[str],
    *,
    workspace_root_resolver: WorkspaceRootResolver | None,
    state_home_resolver: StateHomeResolver | None = None,
    artifact_path_resolver: ArtifactPathResolver | None = None,
    cwd: Path | None = None,
    environment: Mapping[str, str] | None = None,
    restore_path: Callable[[Path], None] = restore_sudo_ownership,
) -> tuple[tuple[Path, OSError], ...]:
    """Restore the sudo caller's ownership for one application invocation.

    The roots include the application's managed state, its resolved workspace,
    and any edition-specific paths returned by ``artifact_path_resolver``.
    Failures are returned to the launcher so it can report warnings without
    changing the invocation's exit status.
    """
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        return ()

    env = os.environ if environment is None else environment
    try:
        uid = int(env["SUDO_UID"])
    except (KeyError, ValueError):
        return ()
    if uid <= 0:
        return ()

    try:
        import pwd

        owner = pwd.getpwuid(uid)
    except (ImportError, KeyError, ValueError):
        return ()
    owner_home = Path(owner.pw_dir)
    try:
        gid = int(env.get("SUDO_GID", owner.pw_gid))
    except ValueError:
        gid = owner.pw_gid

    invocation = Invocation(
        tuple(arguments),
        Path.cwd() if cwd is None else cwd,
        dict(env),
    )
    paths: list[Path] = []

    state_home = owner_home / ".local" / "state"
    if state_home_resolver is not None:
        state_context = StateHomeContext(
            application_id,
            f"posix:{uid}:{gid}",
            owner_home,
            True,
        )
        try:
            resolved_state_home = Path(state_home_resolver(state_context))
            if resolved_state_home.is_absolute():
                state_home = resolved_state_home
        except (OSError, RuntimeError, TypeError, ValueError):
            pass
    paths.append(state_home / application_id)

    if not any(argument in {"-h", "--help"} for argument in arguments):
        if workspace_root_resolver is None:
            paths.append(invocation.cwd)
        else:
            workspace_context = WorkspaceContext(application_id, invocation)
            try:
                paths.append(Path(workspace_root_resolver(workspace_context)))
            except (OSError, RuntimeError, TypeError, ValueError):
                paths.append(invocation.cwd)

    if artifact_path_resolver is not None:
        try:
            paths.extend(
                Path(path)
                for path in artifact_path_resolver(application_id, invocation)
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            pass

    failures: list[tuple[Path, OSError]] = []
    for path in dict.fromkeys(paths):
        try:
            restore_path(path)
        except OSError as error:
            failures.append((path, error))
    return tuple(failures)


def warn_sudo_ownership_failures(
    failures: Iterable[tuple[Path, OSError]],
    *,
    application_id: str = "engulf-clab",
) -> None:
    """Report ownership restoration failures without masking command results."""
    for path, error in failures:
        print(
            f"{application_id}: warning: could not restore ownership for "
            f"{path}: {error}",
            file=sys.stderr,
        )


def _chown_root_owned(path: Path, uid: int, gid: int) -> None:
    metadata = path.stat(follow_symlinks=False)
    if metadata.st_uid != 0 or metadata.st_mode & (stat.S_ISUID | stat.S_ISGID):
        return
    os.chown(path, uid, gid, follow_symlinks=False)
