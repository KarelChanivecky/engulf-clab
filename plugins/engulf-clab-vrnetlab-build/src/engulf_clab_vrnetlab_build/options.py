from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from engulf_clab_ensure_vrnetlab import vrnetlab_type_env
from engulf_executable_wrapper_api import CompletionCandidate, CompletionContext

from .errors import VrnetlabError
from .topology import load_topology, topology_nodes, topology_path_from_args

IMAGE_OPTION = "--eclab-vrnetlab-image"
DEFAULT_IMAGE_SELECTOR = "default"


@dataclass(frozen=True, slots=True)
class ParsedImageOptions:
    arguments: tuple[str, ...]
    selectors: Mapping[str, str]
    removals: frozenset[int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "selectors", MappingProxyType(dict(self.selectors)))


def parse_image_options(arguments: tuple[str, ...]) -> ParsedImageOptions:
    """Extract repeatable image selectors without mutating the original call."""
    selectors: dict[str, str] = {}
    removals: set[int] = set()
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--":
            break
        if argument == IMAGE_OPTION:
            if index + 1 >= len(arguments) or arguments[index + 1] == "--":
                raise VrnetlabError(f"{IMAGE_OPTION} requires NODE=PATH")
            value = arguments[index + 1]
            removals.update((index, index + 1))
            index += 2
        elif argument.startswith(f"{IMAGE_OPTION}="):
            value = argument.removeprefix(f"{IMAGE_OPTION}=")
            removals.add(index)
            index += 1
        else:
            index += 1
            continue

        target, source = _parse_selector(value)
        if target in selectors:
            raise VrnetlabError(f"{IMAGE_OPTION} repeats image selector {target!r}")
        selectors[target] = source

    normalized = tuple(
        argument for position, argument in enumerate(arguments) if position not in removals
    )
    return ParsedImageOptions(normalized, selectors, frozenset(removals))


def complete_image_option(context: CompletionContext) -> Iterable[CompletionCandidate]:
    """Complete selector names from the chosen topology and paths after ``=``."""
    topology_path, node_names = _completion_topology(context.words)
    current = context.current
    if "=" in current:
        target, path_prefix = current.split("=", 1)
        if target != DEFAULT_IMAGE_SELECTOR and target not in node_names:
            return ()
        base = Path.cwd() if topology_path is None else topology_path.parent
        return tuple(
            CompletionCandidate(f"{target}={candidate}")
            for candidate in _path_candidates(path_prefix, base=base)
        )

    used = _used_selectors(context.words[: context.cursor_index])
    targets = (DEFAULT_IMAGE_SELECTOR, *node_names)
    return tuple(
        CompletionCandidate(
            f"{target}=",
            (
                "Fallback image source"
                if target == DEFAULT_IMAGE_SELECTOR
                else f"Image source for node {target}"
            ),
        )
        for target in targets
        if target not in used and f"{target}=".startswith(current)
    )


def _parse_selector(value: str) -> tuple[str, str]:
    target, separator, source = value.partition("=")
    if not separator:
        # Preserve the original single-path form while normalizing it internally.
        target, source = DEFAULT_IMAGE_SELECTOR, value
    if not target or not source or target.strip() != target or not source.strip():
        raise VrnetlabError(
            f"{IMAGE_OPTION} requires NODE=PATH; use {DEFAULT_IMAGE_SELECTOR}=PATH "
            "for the fallback source"
        )
    return target, source


def _used_selectors(arguments: tuple[str, ...]) -> frozenset[str]:
    used: set[str] = set()
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--":
            break
        if argument == IMAGE_OPTION:
            if index + 1 >= len(arguments):
                break
            value = arguments[index + 1]
            index += 2
        elif argument.startswith(f"{IMAGE_OPTION}="):
            value = argument.removeprefix(f"{IMAGE_OPTION}=")
            index += 1
        else:
            index += 1
            continue
        try:
            target, _source = _parse_selector(value)
        except VrnetlabError:
            continue
        used.add(target)
    return frozenset(used)


def _completion_topology(arguments: tuple[str, ...]) -> tuple[Path | None, tuple[str, ...]]:
    try:
        path = topology_path_from_args(arguments)
        document = load_topology(path)
        type_environment = vrnetlab_type_env()
        names: list[str] = []
        for node in topology_nodes(document):
            environment = node.data.get("env")
            if not isinstance(environment, Mapping):
                continue
            builder_type = environment.get(type_environment)
            if (
                node.name != DEFAULT_IMAGE_SELECTOR
                and isinstance(builder_type, str)
                and builder_type.strip()
            ):
                names.append(node.name)
        return path, tuple(names)
    except (OSError, VrnetlabError):
        return None, ()


def _path_candidates(current: str, *, base: Path) -> tuple[str, ...]:
    separator = current.rfind("/")
    shown_parent = current[: separator + 1] if separator >= 0 else ""
    prefix = current[separator + 1 :]
    try:
        entered_parent = Path(shown_parent or ".").expanduser()
        directory = entered_parent if entered_parent.is_absolute() else base / entered_parent
        entries = sorted(directory.iterdir(), key=lambda item: item.name)
    except (OSError, RuntimeError):
        return ()
    result: list[str] = []
    for entry in entries:
        if not entry.name.startswith(prefix):
            continue
        value = f"{shown_parent}{entry.name}"
        if entry.is_dir():
            value += "/"
        result.append(value)
    return tuple(result)
