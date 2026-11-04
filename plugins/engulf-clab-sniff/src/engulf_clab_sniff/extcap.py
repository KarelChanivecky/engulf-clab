from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from types import FrameType
from typing import Any

from .arguments import sanitize_tcpdump_arguments
from .errors import SniffError

INTERFACE = "eclab_sniff"
PLAN_ENVIRONMENT_VARIABLE = "ECLAB_SNIFF_EXTCAP_PLAN"
SignalHandler = Callable[[int, FrameType | None], Any] | int | None
_STDERR_TAIL_LIMIT = 64 * 1024


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eclab-sniff-extcap", allow_abbrev=False)
    parser.add_argument("--extcap-interfaces", action="store_true")
    parser.add_argument("--extcap-interface")
    parser.add_argument("--extcap-dlts", action="store_true")
    parser.add_argument("--extcap-config", action="store_true")
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--fifo")
    parser.add_argument("--extcap-capture-filter")
    parser.add_argument("--extcap-version", nargs="?")
    options, _unknown = parser.parse_known_args(arguments)

    if options.extcap_interfaces:
        try:
            _command, raw_display = _read_plan()
            display = _escape_sentence_value(raw_display)
        except (OSError, ValueError, KeyError, TypeError) as problem:
            print(f"eclab sniff extcap: {problem}", file=sys.stderr)
            return 1
        print("extcap {version=1.0}")
        print(f"interface {{value={INTERFACE}}}{{display={display}}}")
        return 0

    if options.extcap_interface != INTERFACE:
        print("eclab sniff extcap: unknown capture interface", file=sys.stderr)
        return 1
    if options.extcap_dlts:
        print("dlt {number=1}{name=EN10MB}{display=Ethernet}")
        return 0
    if options.extcap_config:
        return 0
    if options.extcap_capture_filter is not None and not options.capture:
        try:
            _capture_filter_tokens(options.extcap_capture_filter)
        except SniffError as problem:
            print(f"eclab sniff extcap: {problem}", file=sys.stderr)
            return 1
        return 0
    if not options.capture:
        parser.print_usage(sys.stderr)
        return 2
    if not options.fifo:
        print(
            "eclab sniff extcap: Wireshark did not provide a packet FIFO",
            file=sys.stderr,
        )
        return 2

    try:
        command, _display = _read_plan()
        command = _capture_command(command, options.extcap_capture_filter)
        return _capture(command, Path(options.fifo))
    except (OSError, ValueError, KeyError, TypeError, SniffError) as problem:
        print(f"eclab sniff extcap: {problem}", file=sys.stderr)
        return 1


def _read_plan() -> tuple[list[str], str]:
    plan_path = os.environ.get(PLAN_ENVIRONMENT_VARIABLE)
    if not plan_path:
        raise ValueError("capture plan path is not set")
    with Path(plan_path).open(encoding="utf-8") as plan_file:
        plan = json.load(plan_file)
    if not isinstance(plan, dict):
        raise TypeError("capture plan is invalid")
    command = plan.get("command")
    display = plan.get("display")
    if (
        not isinstance(command, list)
        or not command
        or any(not isinstance(argument, str) for argument in command)
        or not isinstance(display, str)
    ):
        raise ValueError("capture plan is invalid")
    return command, display


def _escape_sentence_value(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def _capture_filter_tokens(expression: str | None) -> tuple[str, ...]:
    if expression is None or not expression.strip():
        return ()
    try:
        arguments = tuple(shlex.split(expression))
    except ValueError as problem:
        raise SniffError(f"invalid Wireshark capture filter: {problem}") from problem
    sanitized = sanitize_tcpdump_arguments(arguments)
    if sanitized.options:
        raise SniffError("Wireshark capture filter must be a BPF expression")
    return sanitized.filter_expression


def _capture_command(command: list[str], capture_filter: str | None) -> list[str]:
    result = list(command)
    extra_filter = _capture_filter_tokens(capture_filter)
    if not extra_filter:
        return result

    try:
        marker = result.index("--")
    except ValueError:
        result.extend(("--", *extra_filter))
        return result

    original_filter = result[marker + 1 :]
    if not original_filter:
        result.extend(extra_filter)
    else:
        result[marker + 1 :] = [
            "(",
            *original_filter,
            ")",
            "and",
            "(",
            *extra_filter,
            ")",
        ]
    return result


def _capture(command: list[str], fifo: Path) -> int:
    stopped = False
    capture: subprocess.Popen[bytes] | None = None
    stderr_reader: threading.Thread | None = None
    stderr_tail = bytearray()

    def stop_capture(_signum: int, _frame: object) -> None:
        nonlocal stopped
        stopped = True
        if capture is not None and capture.poll() is None:
            try:
                capture.send_signal(signal.SIGINT)
            except ProcessLookupError:
                pass

    previous_handlers: dict[signal.Signals, SignalHandler] = {}
    for stop_signal in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[stop_signal] = signal.signal(stop_signal, stop_capture)

    try:
        with fifo.open("wb", buffering=0) as packet_stream:
            capture = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=packet_stream,
                stderr=subprocess.PIPE,
            )
            assert capture.stderr is not None
            stderr_reader = threading.Thread(
                target=_drain_stderr,
                args=(capture.stderr, stderr_tail),
                daemon=True,
            )
            stderr_reader.start()
            if stopped:
                stop_capture(signal.SIGTERM, None)
            result = capture.wait()
            stderr_reader.join()
        if result in {141, -signal.SIGPIPE} or (
            stopped and result in {130, -signal.SIGINT}
        ):
            return 0
        if result != 0:
            _write_capture_error(stderr_tail, result)
        return result
    except BrokenPipeError:
        if capture is not None and capture.poll() is None:
            stop_capture(signal.SIGPIPE, None)
            capture.wait()
        return 0
    except KeyboardInterrupt:
        stop_capture(signal.SIGINT, None)
        if capture is not None:
            capture.wait()
        return 130
    finally:
        if capture is not None and capture.poll() is None:
            stop_capture(signal.SIGTERM, None)
            capture.wait()
        if stderr_reader is not None:
            stderr_reader.join()
        for stop_signal, previous_handler in previous_handlers.items():
            signal.signal(stop_signal, previous_handler)


def _drain_stderr(stream: Any, output: bytearray) -> None:
    while chunk := stream.read(4096):
        output.extend(chunk)
        if len(output) > _STDERR_TAIL_LIMIT:
            del output[: len(output) - _STDERR_TAIL_LIMIT]


def _write_capture_error(stderr_tail: bytearray, return_code: int) -> None:
    diagnostic = stderr_tail.decode("utf-8", errors="replace").strip()
    if diagnostic:
        print(diagnostic, file=sys.stderr)
    else:
        print(
            f"eclab sniff extcap: capture helper exited with status {return_code}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    raise SystemExit(main())
