"""Console entry point for the standard Containerlab application definition."""

from __future__ import annotations

import importlib.metadata
import re
import sys
from pathlib import Path

from engulf import FRAMEWORK_ERROR_EXIT, GoalPrivilegeError

from .app import CONTAINERLAB_APPLICATION


def main() -> int:
    """Run the standard Containerlab application.

    eclab has not opted its goal into elevated startup, so Engulf refuses to
    construct the application in a privileged process. Report that refusal on
    stderr and exit with the framework error code instead of a traceback.
    """
    arguments = tuple(sys.argv[1:])
    if len(arguments) == 2 and arguments[0] == "--eclab-freeze-compatible":
        return _compatible(Path(arguments[1]))
    try:
        with CONTAINERLAB_APPLICATION.create() as application:
            return application.run()
    except GoalPrivilegeError as error:
        print(f"eclab: {error}", file=sys.stderr)
        return FRAMEWORK_ERROR_EXIT


def _compatible(requirements: Path) -> int:
    """Return success only when this executable has the frozen package versions."""
    try:
        lines = requirements.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 1
    for line in lines:
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s]+)", line.strip())
        if match is None:
            continue
        try:
            installed = importlib.metadata.version(match.group(1))
        except importlib.metadata.PackageNotFoundError:
            return 1
        if installed != match.group(2):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
