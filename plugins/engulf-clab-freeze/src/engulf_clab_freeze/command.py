"""Implementation of the ``eclab freeze`` control command."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml
from engulf_clab_lab_parser.session import (
    TopologyError,
    load_topology,
    topology_path_from_args,
)
from engulf_clab_vrnetlab_build.config import build_requests_from_topology

_BUILTIN_IGNORES = frozenset(
    {".git", ".engulf-clab", ".venv", ".eclab-venv", "__pycache__", "build", "dist"}
)
_LICENSE_SUFFIXES = (".lic", ".license", ".licence")
_FREEZE_KEY = "x-engulf-clab-freeze"


class FreezeError(RuntimeError):
    """A lab cannot safely be turned into a portable archive."""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eclab freeze")
    parser.add_argument("-t", "--topo", "--topology", required=True, metavar="TOPOLOGY")
    parser.add_argument("--output", required=True, metavar="ARCHIVE")
    arguments = parser.parse_args(argv)
    try:
        topology = topology_path_from_args(("-t", arguments.topology))
        archive = Path(arguments.output).expanduser().resolve()
        freeze(topology, archive)
    except (FreezeError, TopologyError, OSError, yaml.YAMLError) as error:
        print(f"eclab freeze: {error}", file=sys.stderr)
        return 1
    return 0


def freeze(topology_path: Path, archive: Path) -> None:
    """Create an atomic, sanitized ``.tar.gz`` archive from one topology."""
    if not archive.name.endswith((".tar.gz", ".tgz")):
        raise FreezeError("--output must end in .tar.gz or .tgz")
    if archive.exists():
        raise FreezeError(f"output already exists: {archive}")
    if not archive.parent.is_dir():
        raise FreezeError(f"output parent does not exist: {archive.parent}")
    source_root = topology_path.parent.resolve()
    generated_licenses = source_root / ".engulf-clab" / "licenses"
    if generated_licenses.exists():
        raise FreezeError("destroy the lab before freezing; generated license copies exist")

    source = load_topology(topology_path)
    _reject_external_symlinks(source_root, _ignore_patterns(source_root))
    root_name = _archive_root_name(archive)
    with tempfile.TemporaryDirectory(prefix=".eclab-freeze-", dir=archive.parent) as work:
        staging = Path(work) / root_name
        warnings = _copy_source(source_root, staging, _ignore_patterns(source_root))
        copied_topology = staging / topology_path.name
        if not copied_topology.is_file():
            raise FreezeError("topology was excluded by the freeze ignore rules")
        frozen = _freeze_topology(copied_topology, source, source_root, staging, warnings)
        (staging / ".eclab-freeze.env").write_text(
            _frozen_environment(frozen["tools"]), encoding="utf-8"
        )
        packages = _locked_packages()
        (staging / "requirements.freeze.txt").write_text(
            "\n".join(f"{name}=={version}" for name, version in packages) + "\n",
            encoding="utf-8",
        )
        _download_wheels(staging, warnings)
        (staging / "FREEZE-WARNINGS.txt").write_text(
            "\n".join(f"- {warning}" for warning in warnings) + ("\n" if warnings else ""),
            encoding="utf-8",
        )
        (staging / "run-eclab.sh").write_text(_launcher(topology_path.name), encoding="utf-8")
        os.chmod(staging / "run-eclab.sh", 0o755)
        temporary_archive = Path(work) / archive.name
        with tarfile.open(temporary_archive, "w:gz") as tar:
            tar.add(staging, arcname=root_name, recursive=True)
        temporary_archive.replace(archive)


def _archive_root_name(archive: Path) -> str:
    name = archive.name.removesuffix(".tar.gz").removesuffix(".tgz")
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-") or "frozen-lab"


def _ignore_patterns(root: Path) -> tuple[str, ...]:
    ignore = root / ".eclab-freezeignore"
    if not ignore.is_file():
        return ()
    return tuple(
        line.strip() for line in ignore.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def _ignored(relative: Path, patterns: Iterable[str]) -> bool:
    text = relative.as_posix()
    return relative.name in _BUILTIN_IGNORES or any(
        fnmatch.fnmatch(text, pattern) or fnmatch.fnmatch(relative.name, pattern)
        for pattern in patterns
    )


def _reject_external_symlinks(root: Path, patterns: tuple[str, ...]) -> None:
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if _ignored(relative, patterns):
            continue
        if path.is_symlink() and not path.resolve().is_relative_to(root):
            raise FreezeError(f"symlink escapes the lab directory: {relative}")


def _copy_source(root: Path, destination: Path, patterns: tuple[str, ...]) -> list[str]:
    warnings: list[str] = []

    def ignore(directory: str, names: list[str]) -> set[str]:
        base = Path(directory)
        excluded: set[str] = set()
        for name in names:
            relative = (base / name).relative_to(root)
            if _ignored(relative, patterns):
                excluded.add(name)
            elif (base / name).is_file() and name.lower().endswith(_LICENSE_SUFFIXES):
                excluded.add(name)
                warnings.append(f"excluded possible license file: {relative}")
        return excluded

    shutil.copytree(root, destination, symlinks=True, ignore=ignore)
    return warnings


def _freeze_topology(
    copied_path: Path,
    original: dict[str, Any],
    source_root: Path,
    staging_root: Path,
    warnings: list[str],
) -> dict[str, Any]:
    copied = yaml.safe_load(copied_path.read_text(encoding="utf-8"))
    if not isinstance(copied, dict):
        raise FreezeError("topology must contain a YAML mapping")
    topology = copied.get("topology")
    nodes = topology.get("nodes") if isinstance(topology, dict) else None
    if not isinstance(nodes, dict):
        raise FreezeError("topology.nodes is required")
    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        if "license" in node:
            node["license"] = "__ECLAB_LICENSE_PROMPT__"
        environment = node.get("env")
        if isinstance(environment, dict):
            for key in tuple(environment):
                if isinstance(key, str) and key.endswith("_LIC_CLAMP"):
                    environment.pop(key)
    _copy_external_vrnetlab_inputs(copied, copied_path, source_root, staging_root, warnings)
    copied[_FREEZE_KEY] = {
        "format": 1,
        "application": "engulf-clab",
        "packages": [{"name": name, "version": version} for name, version in _locked_packages()],
        "tools": _tool_provenance(),
        "licenses": "prompt",
    }
    copied_path.write_text(yaml.safe_dump(copied, sort_keys=False), encoding="utf-8")
    return copied[_FREEZE_KEY]


def _copy_external_vrnetlab_inputs(
    topology: dict[str, Any], path: Path, source_root: Path, staging: Path, warnings: list[str]
) -> None:
    try:
        requests = build_requests_from_topology(path, topology, os.environ)
    except Exception as error:  # A best-effort freeze should retain an unresolved source.
        warnings.append(f"could not resolve vrnetlab image inputs: {error}")
        return
    nodes = topology.get("topology", {}).get("nodes", {})
    if not isinstance(nodes, dict):
        return
    for request in requests:
        source = request.source
        if source is None:
            continue
        if not source.is_file():
            warnings.append(f"vrnetlab source is unavailable: {source}")
            continue
        if source.is_relative_to(source_root):
            continue
        target = staging / "assets" / "images" / request.node_name / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        node = nodes.get(request.node_name)
        if isinstance(node, dict):
            environment = node.setdefault("env", {})
            if isinstance(environment, dict):
                environment["ECLAB_VRNETLAB_IMG_PATH"] = str(target.relative_to(staging))
        warnings.append(f"copied external vrnetlab input for {request.node_name}: sha256={_sha256(target)}")


def _tool_provenance() -> dict[str, object]:
    return {
        "containerlab": _git_provenance(os.environ.get("CONTAINERLAB_DIR")),
        "vrnetlab": _git_provenance(os.environ.get("VRNETLAB_DIR")),
    }


def _frozen_environment(tools: object) -> str:
    if not isinstance(tools, dict):
        return ""
    lines = ["# Generated by eclab freeze. Do not add secrets here."]
    for label, prefix in (("containerlab", "CONTAINERLAB"), ("vrnetlab", "VRNETLAB")):
        value = tools.get(label)
        if not isinstance(value, dict):
            continue
        repository, revision = value.get("repository"), value.get("revision")
        if isinstance(repository, str) and isinstance(revision, str):
            lines.append(f"export {prefix}_REPO={_shell_quote(repository)}")
            lines.append(f"export {prefix}_VERSION={_shell_quote(revision)}")
    return "\n".join(lines) + "\n"


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\\"'\\\"'") + "'"


def _git_provenance(value: str | None) -> dict[str, str] | None:
    if not value:
        return None
    root = Path(value).expanduser()
    if not (root / ".git").exists():
        return {"path": str(root), "status": "unmanaged"}
    try:
        revision = _run_git(root, "rev-parse", "HEAD")
        remote = _run_git(root, "remote", "get-url", "origin")
    except FreezeError:
        return {"path": str(root), "status": "unverifiable"}
    return {"repository": remote, "revision": revision}


def _run_git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], text=True, capture_output=True, check=False)
    if result.returncode:
        raise FreezeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def _locked_packages() -> list[tuple[str, str]]:
    names = {"engulf-clab"}
    for group in (
        "engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper",
        "engulf.plugins.v1.application.engulf_clab",
    ):
        for point in importlib.metadata.entry_points(group=group):
            if point.dist is not None:
                names.add(point.dist.name)
    resolved: dict[str, str] = {}
    pending = list(names)
    while pending:
        name = pending.pop()
        normalized = name.lower().replace("_", "-")
        if normalized in resolved:
            continue
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            continue
        resolved[normalized] = distribution.version
        for requirement in distribution.requires or ():
            dependency = re.split(r"[ ;(<>=!~\[]", requirement, maxsplit=1)[0]
            if dependency:
                pending.append(dependency)
    return sorted(resolved.items())


def _download_wheels(staging: Path, warnings: list[str]) -> None:
    wheelhouse = staging / "wheelhouse"
    wheelhouse.mkdir()
    result = subprocess.run(
        [sys.executable, "-m", "pip", "download", "--dest", str(wheelhouse), "-r", str(staging / "requirements.freeze.txt")],
        text=True, capture_output=True, check=False,
    )
    if result.returncode:
        warnings.append("could not obtain a complete wheelhouse; launcher will fall back to its package index")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _launcher(topology_name: str) -> str:
    return f'''#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${{BASH_SOURCE[0]}}")" && pwd)"
requirements="$root/requirements.freeze.txt"
wheelhouse="$root/wheelhouse"
source "$root/.eclab-freeze.env"
existing="$(command -v eclab || true)"
runner=""
if [[ -n "$existing" ]] && "$existing" --eclab-freeze-compatible "$requirements" >/dev/null 2>&1; then
    runner="$existing"
elif [[ -n "$existing" && -t 0 ]]; then
    read -r -p "Installed eclab differs from this freeze. Run it anyway? [y/N] " answer
    [[ "$answer" =~ ^[Yy]$ ]] && runner="$existing"
fi
if [[ -z "$runner" && -z "$existing" && -t 0 ]]; then
    read -r -p "No eclab found. Install frozen packages into your user site? [y/N] " answer
    if [[ "$answer" =~ ^[Yy]$ ]]; then
        python3 -m pip install --user --find-links "$wheelhouse" -r "$requirements"
        runner="$(command -v eclab)"
    fi
fi
if [[ -z "$runner" ]]; then
    venv="$root/.eclab-venv"
    if [[ ! -x "$venv/bin/eclab" ]]; then
        python3 -m venv "$venv"
        "$venv/bin/python" -m pip install --find-links "$wheelhouse" -r "$requirements"
    fi
    runner="$venv/bin/eclab"
fi
if [[ $# -eq 0 ]]; then set -- deploy -t {topology_name!s}; fi
exec "$runner" "$@"
'''
