from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import BinaryIO

from engulf_api import PluginLogger
from engulf_clab_lab_parser import (
    TopologyError,
    derived_topology_path,
    load_topology,
    topology_path_from_args,
)

from .arguments import (
    TCPDUMP_IMAGE,
    SniffRequest,
    parse_request,
    sanitize_tcpdump_arguments,
)
from .docker import DockerClient, DockerError
from .errors import SniffError
from .topology import choose_interface, topology_lab_name, topology_nodes


def main(
    arguments: tuple[str, ...],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    program: str = "eclab sniff",
    logger: PluginLogger,
    docker: DockerClient | None = None,
) -> int:
    try:
        request = parse_request(arguments)
        topology_args = (
            () if request.topology is None else ("--topology", request.topology)
        )
        topology_path = topology_path_from_args(topology_args, cwd)
        deployed_topology = derived_topology_path(topology_path)
        if deployed_topology.is_file():
            topology_path = deployed_topology
        document = load_topology(topology_path, environment)
        nodes = set(topology_nodes(document))
        for node in (request.node1, request.node2):
            if node not in nodes:
                raise SniffError(f"node {node!r} is not declared in {topology_path}")
        if request.node1 == request.node2:
            raise SniffError("NODE1 and NODE2 must be different nodes")
        interface = choose_interface(
            document, request.node1, request.node2, request.interface
        )
        tcpdump = sanitize_tcpdump_arguments(request.tcpdump_arguments)
        lab_name = topology_lab_name(document, topology_path)
        client = docker or DockerClient()
        container = client.find_node(
            lab_name=lab_name,
            node_name=request.node1,
            topology_path=topology_path,
        )
        output, output_stream = _prepare_capture_output(request, cwd)
    except (DockerError, OSError, SniffError, TopologyError) as problem:
        logger.error("%s: %s", program, problem)
        return 2

    command = _docker_command(
        container_id=container.identifier,
        interface=interface,
        options=tcpdump.options,
        filter_expression=tcpdump.filter_expression,
        pcap_output=output is not None or request.wireshark,
    )
    if request.wireshark:
        return _run_wireshark_capture(
            command,
            display=f"{request.node1} ↔ {request.node2} ({interface})",
            environment=environment,
            logger=logger,
            program=program,
        )

    try:
        process = subprocess.Popen(command, stdout=output_stream)
        try:
            result = process.wait()
        except KeyboardInterrupt:
            try:
                process.send_signal(signal.SIGINT)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait()
            result = 130
    except KeyboardInterrupt:
        result = 130
    except OSError as problem:
        logger.error("%s: could not start Docker capture helper: %s", program, problem)
        if output is not None:
            _remove_empty_capture(output)
        return 1
    finally:
        if output_stream is not None:
            output_stream.close()
    if result and output is not None:
        _remove_empty_capture(output)
    return result


def _run_wireshark_capture(
    command: list[str],
    *,
    display: str,
    environment: Mapping[str, str],
    logger: PluginLogger,
    program: str,
) -> int:
    child_environment = os.environ.copy()
    child_environment.update(environment)
    launcher = _find_extcap_launcher(child_environment)
    if launcher is None:
        logger.error(
            "%s: could not find the eclab-sniff-extcap executable on PATH", program
        )
        return 1

    try:
        with tempfile.TemporaryDirectory(prefix="eclab-sniff-") as temporary_directory:
            extcap_directory = Path(temporary_directory)
            plan_path = extcap_directory / "capture-plan.json"
            _write_extcap_plan(plan_path, command=command, display=display)
            os.symlink(launcher, extcap_directory / "eclab-sniff-extcap")
            extcap_paths = _wireshark_extcap_paths(child_environment)
            child_environment["WIRESHARK_EXTCAP_DIR"] = os.pathsep.join(
                (str(extcap_directory), *extcap_paths)
            )
            child_environment["ECLAB_SNIFF_EXTCAP_PLAN"] = str(plan_path)
            try:
                wireshark = subprocess.Popen(
                    ("wireshark", "-i", "eclab_sniff", "-k"),
                    env=child_environment,
                )
            except OSError as problem:
                logger.error("%s: could not start Wireshark: %s", program, problem)
                return 1
            try:
                return wireshark.wait()
            except KeyboardInterrupt:
                _stop_process(wireshark, signal.SIGINT)
                return 130
    except OSError as problem:
        logger.error("%s: could not start Wireshark capture: %s", program, problem)
        return 1


def _find_extcap_launcher(environment: Mapping[str, str]) -> str | None:
    launcher = shutil.which("eclab-sniff-extcap", path=environment.get("PATH"))
    if launcher is not None:
        return str(Path(launcher).resolve())
    executable_directory = Path(sys.executable).parent
    for filename in ("eclab-sniff-extcap", "eclab-sniff-extcap.exe"):
        candidate = executable_directory / filename
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _write_extcap_plan(path: Path, *, command: list[str], display: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as plan_file:
        json.dump({"command": command, "display": display}, plan_file)


def _wireshark_extcap_paths(environment: Mapping[str, str]) -> tuple[str, ...]:
    wireshark = shutil.which("tshark", path=environment.get("PATH")) or shutil.which(
        "wireshark", path=environment.get("PATH")
    )
    paths: list[str] = []
    if wireshark is not None:
        try:
            result = subprocess.run(
                (wireshark, "-G", "folders"),
                capture_output=True,
                check=False,
                env=dict(environment),
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            result = None
        if result is not None and result.returncode == 0:
            for line in result.stdout.splitlines():
                label, separator, value = line.partition(":")
                if separator and label.strip().lower() in {
                    "extcap path",
                    "global extcap path",
                    "personal extcap path",
                }:
                    paths.extend(
                        path.strip() for path in value.split(os.pathsep) if path.strip()
                    )

    if not paths:
        paths.extend(
            path.strip()
            for path in environment.get("WIRESHARK_EXTCAP_DIR", "").split(os.pathsep)
            if path.strip()
        )
    return tuple(dict.fromkeys(paths))


def _stop_process(process: subprocess.Popen[bytes], stop_signal: int) -> None:
    if process.poll() is not None:
        return
    try:
        process.send_signal(stop_signal)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def _prepare_capture_output(
    request: SniffRequest, cwd: Path
) -> tuple[Path | None, BinaryIO | None]:
    if request.output is None:
        return None, None
    requested = request.output
    target = requested if requested.is_absolute() else cwd / requested
    parent = target.parent.resolve()
    if not parent.is_dir():
        raise SniffError(f"capture directory does not exist: {parent}")
    filename = target.name
    output = parent / filename
    if any(ord(character) < 32 or ord(character) == 127 for character in str(output)):
        raise SniffError("capture file paths cannot contain control characters")
    if not filename or filename in {".", ".."}:
        raise SniffError("--write must name a file")
    try:
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise SniffError(f"capture output already exists: {output}") from error
    try:
        stream = os.fdopen(descriptor, "wb")
    except OSError:
        try:
            os.close(descriptor)
        except OSError:
            pass
        output.unlink(missing_ok=True)
        raise
    return output, stream


def _docker_command(
    *,
    container_id: str,
    interface: str,
    options: tuple[str, ...],
    filter_expression: tuple[str, ...],
    pcap_output: bool,
) -> list[str]:
    command = [
        "docker",
        "run",
        "--rm",
        "--pull=missing",
        f"--network=container:{container_id}",
        "--cap-drop=ALL",
        "--cap-add=NET_RAW",
    ]
    tcpdump_arguments = ["tcpdump", "-p", "-n", "-i", interface]
    if pcap_output:
        if "-U" not in options:
            tcpdump_arguments.append("-U")
        tcpdump_arguments.extend(("-w", "-"))
    tcpdump_arguments.extend(options)
    if filter_expression:
        tcpdump_arguments.extend(("--", *filter_expression))
    return [*command, TCPDUMP_IMAGE, *tcpdump_arguments]


def _remove_empty_capture(output: Path) -> None:
    try:
        if output.stat().st_size == 0:
            output.unlink()
    except OSError:
        pass
