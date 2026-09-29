from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from engulf import WorkspaceContext

TOPOLOGY_OPTIONS = frozenset(("-t", "--topo", "--topology", "--eclab-topology"))
_NON_FILESYSTEM_TOPOLOGIES = frozenset(("-", "stdin"))
_FREEZE_VALUE_OPTIONS = frozenset(
    (
        "--eclab-output", "--eclab-external-image", "--eclab-bundle-image",
        "--eclab-pki-passphrase-file",
    )
)


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
    if source is None and context.arguments[:1] == ("freeze",):
        source = _freeze_lab_directory(context.arguments[1:])
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


def _freeze_lab_directory(args: Sequence[str]) -> str | None:
    """Find freeze's optional directory without treating known flag values as it."""
    index = 0
    while index < len(args):
        argument = args[index]
        if argument == "--":
            return args[index + 1] if index + 1 < len(args) else None
        if argument in _FREEZE_VALUE_OPTIONS:
            index += 2
            continue
        if argument.startswith("-"):
            index += 1
            continue
        return argument
    return None
