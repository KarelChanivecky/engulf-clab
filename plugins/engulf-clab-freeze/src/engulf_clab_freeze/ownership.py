"""Restore ownership of freeze outputs created through sudo."""

from __future__ import annotations

import os
from pathlib import Path


def restore_sudo_ownership(
    path: Path, *, preserve: tuple[Path, ...] = ()
) -> None:
    """Give root-owned generated output back to the user who invoked sudo.

    Only the requested output tree is visited. Symlinks are never followed, and
    non-root-owned files inside a replaced tree keep their existing ownership.
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
    preserved = {item.absolute() for item in preserve}
    if target.is_symlink() or not target.exists():
        return
    if target.is_dir():
        for directory, child_directories, filenames in os.walk(
            target, topdown=True, followlinks=False
        ):
            current = Path(directory)
            _chown_root_owned(current, uid, gid, preserved)
            retained: list[str] = []
            for name in child_directories:
                child = current / name
                if child.is_symlink():
                    continue
                retained.append(name)
                _chown_root_owned(child, uid, gid, preserved)
            child_directories[:] = retained
            for name in filenames:
                child = current / name
                if not child.is_symlink():
                    _chown_root_owned(child, uid, gid, preserved)
    else:
        _chown_root_owned(target, uid, gid, preserved)


def _chown_root_owned(path: Path, uid: int, gid: int, preserve: set[Path]) -> None:
    if path.absolute() in preserve:
        return
    if path.stat(follow_symlinks=False).st_uid == 0:
        os.chown(path, uid, gid, follow_symlinks=False)
