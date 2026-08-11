from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from engulf import WorkspaceContext

TOPOLOGY_OPTIONS = frozenset(("-t", "--topo", "--topology"))
_NON_FILESYSTEM_TOPOLOGIES = frozenset(("-", "stdin"))


def topology_source_from_args(args: Sequence[str]) -> str | None:
    for index, argument in enumerate(args):
        if argument in TOPOLOGY_OPTIONS:
            if index + 1 >= len(args):
                return None
            return args[index + 1]

        for option in TOPOLOGY_OPTIONS:
            prefix = f"{option}="
            if argument.startswith(prefix):
                return argument[len(prefix) :] or None

    return None


def workspace_root(context: WorkspaceContext) -> Path:
    """Resolve Containerlab workspace state to the topology's directory."""
    source = topology_source_from_args(context.arguments)
    if (
        source is None
        or source.lower() in _NON_FILESYSTEM_TOPOLOGIES
        or "://" in source
    ):
        return context.cwd

    candidate = Path(source).expanduser()
    if not candidate.is_absolute():
        candidate = context.cwd / candidate

    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        return candidate.parent
    return resolved if resolved.is_dir() else resolved.parent
