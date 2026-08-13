"""Installed entry points for the reviewed systemd installation shell scripts."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _script(name: str) -> Path:
    """Locate wheel-included assets beside this installed Python package."""
    packaged = Path(__file__).parent / "scripts" / name
    if packaged.is_file():
        return packaged
    # Source-tree use (including local development validation) keeps the shell
    # assets at the distribution root. Installed wheels always use `packaged`.
    return Path(__file__).parents[2] / "scripts" / name


def _run(name: str, argv: list[str] | None) -> int:
    script = _script(name)
    if not script.is_file():
        print(f"eclab-mcp: packaged installer asset is unavailable: {script}", file=sys.stderr)
        return 1
    arguments = list(sys.argv[1:] if argv is None else argv)
    if name == "install-system.sh":
        executable_directory = Path(sys.executable).resolve().parent
        for option, command in (("--daemon", "eclab-mcpd"), ("--eclab", "eclab")):
            if option in arguments or any(item.startswith(f"{option}=") for item in arguments):
                continue
            candidate = executable_directory / command
            if candidate.is_file():
                arguments.extend((option, str(candidate)))
    result = subprocess.run(["/bin/bash", str(script), *arguments], check=False)
    return result.returncode


def install_main(argv: list[str] | None = None) -> int:
    """Run the packaged root systemd installer."""
    return _run("install-system.sh", argv)


def uninstall_main(argv: list[str] | None = None) -> int:
    """Run the packaged root systemd uninstaller."""
    return _run("uninstall-system.sh", argv)
