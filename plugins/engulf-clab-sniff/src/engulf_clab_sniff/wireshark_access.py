from __future__ import annotations

import os
import shutil
import stat
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_CAPTURE_GROUPS = frozenset({"wireshark", "packetcapture"})


@dataclass(frozen=True, slots=True)
class DumpcapAccessResult:
    group_added: str | None = None
    warning: str | None = None


def add_dumpcap_capture_group(
    username: str,
    environment: Mapping[str, str],
) -> DumpcapAccessResult:
    """Join an existing safe dumpcap group; never alter the system binary."""
    if os.name != "posix":
        return DumpcapAccessResult()

    dumpcap = _find_dumpcap(environment)
    if dumpcap is None:
        return DumpcapAccessResult()

    try:
        metadata = dumpcap.stat()
    except OSError as error:
        return DumpcapAccessResult(warning=f"could not inspect {dumpcap}: {error}")
    if os.access(dumpcap, os.X_OK):
        return DumpcapAccessResult()

    mode = metadata.st_mode
    if (
        not stat.S_ISREG(mode)
        or metadata.st_uid != 0
        or mode & (stat.S_IWGRP | stat.S_IWOTH)
        or not mode & stat.S_IXGRP
    ):
        return DumpcapAccessResult(
            warning=(
                f"{dumpcap} is not safely configured for group execution; "
                "configure Wireshark's capture permissions through the OS package, "
                "then rerun sudoless"
            )
        )

    try:
        import grp

        group_name = grp.getgrgid(metadata.st_gid).gr_name
    except (ImportError, KeyError):
        group_name = ""
    if group_name not in _CAPTURE_GROUPS:
        return DumpcapAccessResult(
            warning=(
                f"{dumpcap} is not owned by a recognized Wireshark capture group; "
                "configure its group through the OS package"
            )
        )

    sudo = shutil.which("sudo", path=environment.get("PATH"))
    if sudo is None:
        return DumpcapAccessResult(
            warning="sudo is unavailable; could not add the Wireshark capture group"
        )
    try:
        subprocess.run(
            (sudo, "--", "usermod", "-aG", group_name, username),
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", None)
        detail = detail.strip() if isinstance(detail, str) else ""
        return DumpcapAccessResult(
            warning=(
                f"could not add {username} to Wireshark capture group {group_name!r}"
                + (f": {detail}" if detail else f": {error}")
            )
        )
    return DumpcapAccessResult(group_added=group_name)


def _find_dumpcap(environment: Mapping[str, str]) -> Path | None:
    search_path = environment.get("PATH", os.environ.get("PATH", os.defpath))
    executable = shutil.which("dumpcap", path=search_path)
    if executable is not None:
        return Path(executable).resolve()

    for directory in search_path.split(os.pathsep):
        candidate = Path(directory or os.curdir) / "dumpcap"
        try:
            if candidate.is_file():
                return candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
    return None
