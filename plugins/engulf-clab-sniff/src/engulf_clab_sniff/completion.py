from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from engulf_api import RegistrationAPI
from engulf_clab_lab_parser import (
    TopologyError,
    derived_topology_path,
    load_topology,
    topology_path_from_args,
)
from engulf_executable_wrapper_api import (
    CompletionCandidate,
    CompletionContext,
    CompletionRegistry,
    Runtime,
)

from .arguments import SAFE_SWITCHES, SAFE_VALUES, VALUE_CHOICES
from .topology import (
    direct_peers,
    linked_interface_pairs,
    linked_interfaces,
    topology_nodes,
)

_BPF_WORDS = (
    "arp",
    "broadcast",
    "icmp",
    "icmp6",
    "ip",
    "ip6",
    "multicast",
    "tcp",
    "udp",
    "port",
    "portrange",
    "host",
    "net",
    "src",
    "dst",
    "vlan",
    "less",
    "greater",
    "not",
    "and",
    "or",
)
_COMMON_PORTS = ("22", "53", "67", "68", "80", "179", "443", "830")


def register_sniff_completions(
    registry: CompletionRegistry, api: RegistrationAPI
) -> None:
    del api
    registry.provider(Runtime("sniff-command-and-arguments", complete_sniff))


def complete_sniff(
    context: CompletionContext,
) -> Iterable[CompletionCandidate]:
    current = context.current
    if context.cursor_index == 0:
        return (
            (CompletionCandidate("sniff", "Capture packets on a direct node link"),)
            if "sniff".startswith(current)
            else ()
        )
    if not context.words or context.words[0] != "sniff":
        return ()

    prior = context.words[1 : context.cursor_index]
    state = _parse_prior(prior)
    if current.startswith("--topology="):
        return tuple(
            CompletionCandidate(f"--topology={item.value}", item.description)
            for item in _path_candidates(current.partition("=")[2], _cwd(context))
        )
    if state.pending == "topology":
        return _path_candidates(current, _cwd(context))
    if state.pending == "write":
        return _path_candidates(current, _cwd(context))

    document = _completion_document(context, state.topology)
    if len(state.nodes) == 0:
        node_candidates = _node_candidates(topology_nodes(document), current)
        extras = tuple(
            CompletionCandidate(flag, description)
            for flag, description in (
                ("--topology", "Select a topology file"),
                ("-t", "Select a topology file"),
            )
            if flag.startswith(current)
        )
        if current.startswith("-"):
            return extras
        return (*node_candidates, *extras)
    if len(state.nodes) == 1:
        node_candidates = _peer_candidates(
            document,
            state.nodes[0],
            direct_peers(document, state.nodes[0]),
            current,
        )
        if current.startswith("-"):
            return tuple(
                CompletionCandidate(flag, "Select a topology file")
                for flag in ("--topology", "-t")
                if flag.startswith(current)
            )
        return node_candidates

    if state.pending == "interface":
        interfaces = linked_interfaces(document, state.nodes[0], state.nodes[1])
        return _value_candidates(interfaces, current, "Node1 interface on this link")
    if state.pending == "tcpdump-value":
        choices = VALUE_CHOICES.get(state.pending_option or "", ())
        return _value_candidates(choices, current)
    if state.pending == "tcpdump-number":
        return ()

    if current.startswith("--interface="):
        prefix = current.partition("=")[2]
        return tuple(
            CompletionCandidate(f"--interface={item}", "Node1 interface on this link")
            for item in linked_interfaces(document, state.nodes[0], state.nodes[1])
            if item.startswith(prefix)
        )
    if current.startswith("--write="):
        return tuple(
            CompletionCandidate(f"--write={item.value}", item.description)
            for item in _path_candidates(current.partition("=")[2], _cwd(context))
        )
    if state.filter_started:
        prior_filter = state.filter_words
        if prior_filter and prior_filter[-1] in {"port", "portrange"}:
            return _value_candidates(_COMMON_PORTS, current, "Common service port")
        if prior_filter and prior_filter[-1] in {"src", "dst"}:
            words = ("host", "net", "port", "portrange")
            return _value_candidates(words, current)
        return _value_candidates(_BPF_WORDS, current, "tcpdump filter keyword")

    candidates: list[CompletionCandidate] = []
    if not state.after_delimiter:
        if "--interface".startswith(current):
            candidates.append(
                CompletionCandidate(
                    "--interface",
                    "Select node1's interface when nodes have multiple links",
                )
            )
        if not state.write and not state.wireshark and "--write".startswith(current):
            candidates.append(
                CompletionCandidate("--write", "Write a pcap file under this host path")
            )
        if (
            not state.wireshark
            and not state.write
            and "--wireshark".startswith(current)
        ):
            candidates.append(
                CompletionCandidate(
                    "--wireshark", "Stream the live capture into Wireshark"
                )
            )
    candidates.extend(
        CompletionCandidate(name, description)
        for name, description in SAFE_SWITCHES
        if name.startswith(current) and name not in state.used_filter_options
    )
    candidates.extend(
        CompletionCandidate(name, f"Set {metavar.lower().replace('_', ' ')}")
        for name, metavar in SAFE_VALUES
        if name.startswith(current) and name not in state.used_filter_options
    )
    if not current.startswith("-"):
        candidates.extend(
            _value_candidates(_BPF_WORDS, current, "tcpdump filter keyword")
        )
    return tuple(candidates)


class _CompletionState:
    def __init__(self) -> None:
        self.nodes: list[str] = []
        self.topology: str | None = None
        self.pending: str | None = None
        self.pending_option: str | None = None
        self.after_delimiter = False
        self.filter_started = False
        self.filter_words: list[str] = []
        self.used_filter_options: set[str] = set()
        self.wireshark = False
        self.write = False


def _parse_prior(words: tuple[str, ...]) -> _CompletionState:
    state = _CompletionState()
    index = 0
    while index < len(words):
        word = words[index]
        if state.pending is not None:
            if state.pending == "topology":
                state.topology = word
            elif state.pending == "interface":
                state.pending = None
                index += 1
                continue
            elif state.pending in {"tcpdump-value", "tcpdump-number"}:
                if state.pending == "tcpdump-value" and state.pending_option == "-Q":
                    state.pending = None
                else:
                    state.pending = None
            elif state.pending == "write":
                state.pending = None
                index += 1
                continue
            state.pending = None
            index += 1
            continue

        if word == "--":
            state.after_delimiter = True
            index += 1
            continue

        if not state.after_delimiter and (
            word == "--topology" or (len(state.nodes) < 2 and word == "-t")
        ):
            state.pending = "topology"
            index += 1
            continue
        if not state.after_delimiter and word.startswith("--topology="):
            state.topology = word.partition("=")[2]
            index += 1
            continue

        if len(state.nodes) < 2:
            if word.startswith("-"):
                index += 1
                continue
            state.nodes.append(word)
            index += 1
            continue

        if not state.after_delimiter and word == "--interface":
            state.pending = "interface"
            index += 1
            continue
        if not state.after_delimiter and word.startswith("--interface="):
            index += 1
            continue
        if not state.after_delimiter and word == "--write":
            state.write = True
            state.pending = "write"
            index += 1
            continue
        if not state.after_delimiter and word.startswith("--write="):
            state.write = True
            index += 1
            continue
        if not state.after_delimiter and word == "--wireshark":
            state.wireshark = True
            index += 1
            continue

        if word in {name for name, _description in SAFE_SWITCHES}:
            state.used_filter_options.add(word)
            index += 1
            continue
        if word in {name for name, _metavar in SAFE_VALUES}:
            state.used_filter_options.add(word)
            state.pending_option = word
            state.pending = "tcpdump-value" if word == "-Q" else "tcpdump-number"
            index += 1
            continue
        if state.filter_started:
            state.filter_words.append(word)
            index += 1
            continue
        if word.startswith("-"):
            state.filter_started = True
        else:
            state.filter_started = True
        state.filter_words.append(word)
        index += 1
    return state


def _completion_document(
    context: CompletionContext, topology_option: str | None
) -> Mapping[str, object]:
    try:
        path_args = () if topology_option is None else ("--topology", topology_option)
        topology_path = topology_path_from_args(path_args, _cwd(context))
        deployed_topology = derived_topology_path(topology_path)
        if deployed_topology.is_file():
            topology_path = deployed_topology
        document = load_topology(topology_path, dict(context.environment))
    except (OSError, RuntimeError, TopologyError):
        return {}
    topology = document.get("topology")
    return document if isinstance(topology, Mapping) else {}


def _node_candidates(
    names: tuple[str, ...], current: str
) -> tuple[CompletionCandidate, ...]:
    return tuple(
        CompletionCandidate(name) for name in names if name.startswith(current)
    )


def _peer_candidates(
    document: Mapping[str, object],
    node1: str,
    peers: tuple[str, ...],
    current: str,
) -> tuple[CompletionCandidate, ...]:
    candidates: list[CompletionCandidate] = []
    for peer in peers:
        if not peer.startswith(current):
            continue
        interface_pairs = linked_interface_pairs(document, node1, peer)
        if interface_pairs:
            description = "; ".join(
                f"{node1}:{left} ↔ {peer}:{right}"
                for left, right in interface_pairs
            )
        else:
            description = "Directly connected peer"
        candidates.append(CompletionCandidate(peer, description))
    return tuple(candidates)


def _value_candidates(
    values: tuple[str, ...], current: str, description: str | None = None
) -> tuple[CompletionCandidate, ...]:
    return tuple(
        CompletionCandidate(value, description)
        for value in values
        if value.startswith(current)
    )


def _cwd(context: CompletionContext) -> Path:
    return Path(context.cwd) if context.cwd is not None else Path.cwd()


def _path_candidates(current: str, base: Path) -> tuple[CompletionCandidate, ...]:
    separator = current.rfind("/")
    shown_parent = current[: separator + 1] if separator >= 0 else ""
    prefix = current[separator + 1 :]
    try:
        entered_parent = Path(shown_parent or ".").expanduser()
        directory = (
            entered_parent if entered_parent.is_absolute() else base / entered_parent
        )
        entries = sorted(directory.iterdir(), key=lambda item: item.name)
    except (OSError, RuntimeError):
        return ()
    candidates: list[CompletionCandidate] = []
    for entry in entries:
        if not entry.name.startswith(prefix):
            continue
        value = f"{shown_parent}{entry.name}"
        if entry.is_dir():
            value += "/"
        candidates.append(CompletionCandidate(value))
    return tuple(candidates)
