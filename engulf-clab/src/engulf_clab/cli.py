"""Console entry point for the standard Containerlab application definition."""

from __future__ import annotations

import importlib.metadata
import re
import sys
from pathlib import Path

from .app import CONTAINERLAB_APPLICATION


def main() -> int:
    """Run the standard Containerlab application."""
    arguments = tuple(sys.argv[1:])
    if arguments and arguments[0] == "freeze":
        return _freeze(arguments[1:])
    if len(arguments) == 2 and arguments[0] == "--eclab-freeze-compatible":
        return _compatible(Path(arguments[1]))
    with CONTAINERLAB_APPLICATION.create() as application:
        return application.run()


def _freeze(arguments: tuple[str, ...]) -> int:
    """Load the optional freeze command without making it an app dependency."""
    points = importlib.metadata.entry_points(group="engulf_clab.freeze_commands")
    point = next((item for item in points if item.name == "freeze"), None)
    if point is None:
        print(
            "eclab freeze requires engulf-clab-freeze; install it or engulf-clab-all-plugins",
            file=sys.stderr,
        )
        return 2
    command = point.load()
    return int(command(list(arguments)))


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
