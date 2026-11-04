from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .errors import SniffError

TCPDUMP_IMAGE = "nicolaka/netshoot:v0.16"

SAFE_SWITCHES: tuple[tuple[str, str], ...] = (
    ("-n", "Do not resolve addresses"),
    ("-nn", "Do not resolve addresses or ports"),
    ("-e", "Print the link-layer header"),
    ("-q", "Print brief packet information"),
    ("-v", "Increase packet detail"),
    ("-vv", "Increase packet detail twice"),
    ("-vvv", "Increase packet detail three times"),
    ("-A", "Print packet payload as ASCII"),
    ("-X", "Print packet payload as hex and ASCII"),
    ("-XX", "Print link-layer header and payload as hex and ASCII"),
    ("-x", "Print packet payload as hex"),
    ("-xx", "Print link-layer header and payload as hex"),
    ("-l", "Flush packet output line by line"),
    ("-U", "Flush packet output promptly"),
    ("-tt", "Print Unix timestamps"),
    ("-ttt", "Print time deltas between packets"),
    ("-tttt", "Print date and time"),
)
SAFE_VALUES: tuple[tuple[str, str], ...] = (
    ("-c", "COUNT"),
    ("-s", "SNAPLEN"),
    ("-B", "BUFFER_KIB"),
    ("-Q", "DIRECTION"),
)
VALUE_CHOICES: dict[str, tuple[str, ...]] = {"-Q": ("in", "out", "inout")}
_INTEGER = re.compile(r"^[0-9]+$")
_FILTER_LIMIT = 4096
_FILTER_TOKEN_LIMIT = 1024
_FILTER_WORDS_LIMIT = 128


@dataclass(frozen=True, slots=True)
class SniffRequest:
    node1: str
    node2: str
    topology: str | None
    interface: str | None
    output: Path | None
    wireshark: bool
    tcpdump_arguments: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TcpdumpArguments:
    options: tuple[str, ...]
    filter_expression: tuple[str, ...]


def parse_request(arguments: tuple[str, ...]) -> SniffRequest:
    nodes: list[str] = []
    topology: str | None = None
    interface: str | None = None
    output: Path | None = None
    wireshark = False
    tcpdump_arguments: list[str] = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--":
            if len(nodes) != 2:
                raise SniffError("provide NODE1 and NODE2 before --")
            tcpdump_arguments.extend(arguments[index + 1 :])
            break

        if argument == "--topology" or (len(nodes) < 2 and argument == "-t"):
            value, index = _separate_value(arguments, index, argument)
            if topology is not None:
                raise SniffError("--topology may be supplied only once")
            topology = value
            continue
        if argument.startswith("--topology="):
            if topology is not None:
                raise SniffError("--topology may be supplied only once")
            topology = argument.partition("=")[2]
            if not topology:
                raise SniffError("--topology requires a topology path")
            index += 1
            continue

        if len(nodes) < 2:
            if argument.startswith("-"):
                raise SniffError(
                    f"unexpected option before both node names: {argument}"
                )
            nodes.append(argument)
            index += 1
            continue

        if argument == "--interface":
            value, index = _separate_value(arguments, index, argument)
            if interface is not None:
                raise SniffError("--interface may be supplied only once")
            interface = value
            continue
        if argument.startswith("--interface="):
            if interface is not None:
                raise SniffError("--interface may be supplied only once")
            interface = argument.partition("=")[2]
            if not interface:
                raise SniffError("--interface requires a node interface")
            index += 1
            continue
        if argument == "--write":
            value, index = _separate_value(arguments, index, argument)
            if output is not None:
                raise SniffError("--write may be supplied only once")
            output = Path(value).expanduser()
            continue
        if argument.startswith("--write="):
            if output is not None:
                raise SniffError("--write may be supplied only once")
            value = argument.partition("=")[2]
            if not value:
                raise SniffError("--write requires a pcap path")
            output = Path(value).expanduser()
            index += 1
            continue
        if argument == "--wireshark":
            if wireshark:
                raise SniffError("--wireshark may be supplied only once")
            wireshark = True
            index += 1
            continue

        tcpdump_arguments.append(argument)
        index += 1

    if len(nodes) != 2:
        raise SniffError(
            "usage: eclab sniff [--topology FILE] NODE1 NODE2 [options] [filter]"
        )
    if wireshark and output is not None:
        raise SniffError("--wireshark and --write cannot be used together")
    return SniffRequest(
        nodes[0],
        nodes[1],
        topology,
        interface,
        output,
        wireshark,
        tuple(tcpdump_arguments),
    )


def sanitize_tcpdump_arguments(arguments: tuple[str, ...]) -> TcpdumpArguments:
    if len(arguments) > _FILTER_WORDS_LIMIT:
        raise SniffError(
            f"tcpdump accepts at most {_FILTER_WORDS_LIMIT} arguments here"
        )
    if sum(len(item.encode("utf-8")) for item in arguments) > _FILTER_LIMIT:
        raise SniffError(f"tcpdump arguments exceed {_FILTER_LIMIT} bytes")
    for item in arguments:
        if not item or any(
            ord(character) < 32 or ord(character) == 127 for character in item
        ):
            raise SniffError(
                "tcpdump arguments cannot contain empty or control characters"
            )
        if len(item.encode("utf-8")) > _FILTER_TOKEN_LIMIT:
            raise SniffError("a tcpdump argument exceeds 1024 bytes")

    options: list[str] = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if not argument.startswith("-"):
            return TcpdumpArguments(tuple(options), arguments[index:])
        if argument in {name for name, _description in SAFE_SWITCHES}:
            options.append(argument)
            index += 1
            continue
        if argument in {name for name, _metavar in SAFE_VALUES}:
            if index + 1 >= len(arguments):
                raise SniffError(f"{argument} requires a value")
            value = arguments[index + 1]
            _validate_option_value(argument, value)
            options.extend((argument, value))
            index += 2
            continue
        raise SniffError(
            f"tcpdump option {argument!r} is not allowed; use a supported option "
            "or an eclab output option"
        )
    return TcpdumpArguments(tuple(options), ())


def _separate_value(
    arguments: tuple[str, ...], index: int, option: str
) -> tuple[str, int]:
    if (
        index + 1 >= len(arguments)
        or not arguments[index + 1]
        or arguments[index + 1] == "--"
    ):
        raise SniffError(f"{option} requires a value")
    return arguments[index + 1], index + 2


def _validate_option_value(option: str, value: str) -> None:
    if option == "-Q":
        if value not in VALUE_CHOICES[option]:
            raise SniffError("-Q must be one of: in, out, inout")
        return
    if _INTEGER.fullmatch(value) is None:
        raise SniffError(f"{option} requires a nonnegative integer")
    number = int(value)
    lower, upper = {
        "-c": (1, 1_000_000),
        "-s": (0, 262_144),
        "-B": (1, 16_384),
    }[option]
    if not lower <= number <= upper:
        raise SniffError(f"{option} must be between {lower} and {upper}")
