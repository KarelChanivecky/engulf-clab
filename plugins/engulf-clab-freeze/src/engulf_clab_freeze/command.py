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
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import yaml  # type: ignore[import-untyped]
from engulf_api import PluginLogger, StateStore
from engulf_clab_ensure_vrnetlab import vrnetlab_image_path_env
from engulf_clab_freeze_api import FreezeContext, discover_contributors
from engulf_clab_freeze_api import FreezeError as ContributorError
from engulf_clab_lab_parser import (
    effective_nodes,
    parse_topology_yaml,
    topology_declarations,
)
from engulf_clab_lab_parser.session import (
    WRITER_TEMP_PREFIX,
    TopologyError,
    load_topology,
    topology_path_from_args,
)
from engulf_clab_vrnetlab_build.config import (
    build_requests_from_topology,
    resolve_image_expression,
)

from .state import FreezeStateError, track_archive, tracked_archives

# Fixed across every edition; must match license-pool's LicenseContract
# label prefix and ensure-vrnetlab's LABEL_PREFIX exactly, since freeze
# writes labels those plugins later read back.
_LABEL_PREFIX = "ECLAB"
_NON_ALPHANUMERIC = re.compile(r"[^A-Z0-9]+")
_BUILTIN_IGNORES = frozenset(
    {
        ".git",
        ".engulf-clab",
        ".venv",
        ".eclab-venv",
        "__pycache__",
        "build",
        "dist",
    }
)
_LICENSE_SUFFIXES = (".lic", ".license", ".licence")
# A lab's `<name>.env` holds owner-private values the topology expands from.
# A freeze archive is made to be handed to someone else, so these never travel
# with it -- the recipient supplies their own.
_PRIVATE_SUFFIXES = (".env",)
_FREEZE_KEY = "x-engulf-clab-freeze"


class FreezeError(RuntimeError):
    """A lab cannot safely be turned into a portable archive."""


def main(
    argv: list[str] | None = None,
    workspace: StateStore | None = None,
    user_state: StateStore | None = None,
    *,
    program: str = "eclab freeze",
    application_name: str = "eclab",
    logger: PluginLogger | None = None,
    environment: Mapping[str, str] | None = None,
) -> int:
    """Run the optional freeze command with an injected workspace state."""
    parser = argparse.ArgumentParser(prog=program)
    parser.add_argument(
        "-t",
        "--topo",
        "--topology",
        dest="topology",
        metavar="TOPOLOGY",
        help="topology to freeze; omit to detect the single lab topology in the current directory",
    )
    parser.add_argument(
        "--output",
        metavar="ARCHIVE",
        help="destination archive (default: <lab-directory>/<lab-directory-name>.tar.gz)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="bundle the eclab runtime, Containerlab, vrnetlab, and lab images for offline use",
    )
    try:
        contributors = discover_contributors()
        for contributor in contributors:
            contributor.add_freeze_arguments(parser)
    except ContributorError as error:
        if logger is None:
            print(f"{program}: {error}", file=sys.stderr)
        else:
            logger.error("%s: %s", program, error)
        return 1
    try:
        arguments = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code or 0)
    try:
        topology_args = ("-t", arguments.topology) if arguments.topology else ()
        topology = topology_path_from_args(topology_args)
        archive = (
            Path(arguments.output).expanduser().resolve()
            if arguments.output
            else _default_archive(topology)
        )
        freeze(
            topology,
            archive,
            workspace=workspace,
            confirm_overwrite=_confirm_overwrite,
            offline=arguments.offline,
            user_state=user_state,
            application_name=application_name,
            environment=environment,
            contributors=contributors,
            contributor_arguments=arguments,
        )
    except (
        FreezeError,
        ContributorError,
        FreezeStateError,
        TopologyError,
        OSError,
        yaml.YAMLError,
    ) as error:
        if logger is None:
            print(f"{program}: {error}", file=sys.stderr)
        else:
            logger.error("%s: %s", program, error)
        return 1
    return 0


def freeze(
    topology_path: Path,
    archive: Path,
    *,
    workspace: StateStore | None = None,
    confirm_overwrite: Callable[[Path], bool] | None = None,
    offline: bool = False,
    user_state: StateStore | None = None,
    application_name: str = "eclab",
    environment: Mapping[str, str] | None = None,
    contributors: tuple[Any, ...] = (),
    contributor_arguments: argparse.Namespace | None = None,
) -> bool:
    """Create an atomic, sanitized ``.tar.gz`` archive from one topology."""
    topology_path = topology_path.expanduser().resolve()
    archive = archive.expanduser().resolve()
    source_root = topology_path.parent.resolve()
    current_environment = os.environ if environment is None else environment
    ignored_archives = tracked_archives(workspace, source_root)
    if not archive.name.endswith((".tar.gz", ".tgz")):
        raise FreezeError("--output must end in .tar.gz or .tgz")
    archive_relative = _relative_to(source_root, archive)
    if archive.exists() or archive.is_symlink():
        if archive.is_symlink() or not archive.is_file():
            raise FreezeError(f"output path is not a regular file: {archive}")
        if confirm_overwrite is None:
            raise FreezeError(f"a file already exists at the output path: {archive}")
        if not confirm_overwrite(archive):
            return False
    if not archive.parent.is_dir():
        raise FreezeError(f"output parent does not exist: {archive.parent}")
    state_directory = _state_directory(application_name)
    generated_license_directories = (
        source_root / state_directory / "licenses",
        source_root / ".engulf-clab" / "licenses",
    )
    if any(path.exists() for path in generated_license_directories):
        raise FreezeError(
            "destroy the lab before freezing; generated license copies exist"
        )

    source = load_topology(topology_path, current_environment)
    patterns = _ignore_patterns(source_root, application_name)
    excluded_paths = set(ignored_archives)
    excluded_paths.add(Path(state_directory))
    if archive_relative is not None:
        excluded_paths.add(archive_relative)
    excluded_paths.add(_containerlab_runtime_directory(source, topology_path))
    _reject_external_symlinks(source_root, patterns, frozenset(excluded_paths))
    root_name = _archive_root_name(archive)
    with tempfile.TemporaryDirectory(
        prefix=".eclab-freeze-", dir=archive.parent
    ) as work:
        temporary_root = Path(work)
        staging = Path(work) / root_name
        ignored_paths = set(excluded_paths)
        try:
            ignored_paths.add(temporary_root.relative_to(source_root))
        except ValueError:
            pass
        warnings = _copy_source(
            source_root, staging, patterns, frozenset(ignored_paths)
        )
        copied_topology = staging / topology_path.name
        if not copied_topology.is_file():
            raise FreezeError("topology was excluded by the freeze ignore rules")
        packages = _locked_packages()
        frozen = _freeze_topology(
            copied_topology,
            source_root,
            staging,
            packages,
            warnings,
            offline=offline,
            environment=current_environment,
        )
        contribution_metadata: dict[str, Any] = {}
        for contributor in contributors:
            contributed = contributor.freeze(
                FreezeContext(
                    source_topology=topology_path,
                    staged_topology=copied_topology,
                    source_root=source_root,
                    staging_root=staging,
                    workspace_state=workspace.directory
                    if workspace is not None
                    else None,
                    user_state=user_state.directory if user_state is not None else None,
                    arguments=contributor_arguments or argparse.Namespace(),
                    environment=current_environment,
                )
            )
            if contributed is not None:
                contribution_metadata[contributor.contributor_id] = dict(contributed)
        if contribution_metadata:
            updated = yaml.safe_load(copied_topology.read_text(encoding="utf-8"))
            if not isinstance(updated, dict):
                raise FreezeError("contributor produced an invalid topology")
            updated[_FREEZE_KEY]["contributors"] = contribution_metadata
            copied_topology.write_text(
                yaml.safe_dump(updated, sort_keys=False), encoding="utf-8"
            )
            frozen["contributors"] = contribution_metadata
        (staging / ".eclab-freeze.env").write_text(
            _frozen_environment(frozen["tools"]), encoding="utf-8"
        )
        (staging / "requirements.freeze.txt").write_text(
            "\n".join(f"{name}=={version}" for name, version in packages) + "\n",
            encoding="utf-8",
        )
        _download_wheels(staging, packages, warnings)
        if offline:
            offline_topology = yaml.safe_load(
                copied_topology.read_text(encoding="utf-8")
            )
            if not isinstance(offline_topology, dict):
                raise FreezeError("frozen topology must contain a YAML mapping")
            _bundle_offline_runtime(staging)
            _bundle_offline_containerlab(staging, user_state, current_environment)
            _bundle_offline_vrnetlab(staging, user_state, current_environment)
            _bundle_offline_images(offline_topology, staging, current_environment)
            copied_topology.write_text(
                yaml.safe_dump(offline_topology, sort_keys=False), encoding="utf-8"
            )
        _prune_empty_directories(staging)
        (staging / "FREEZE-WARNINGS.txt").write_text(
            "\n".join(f"- {warning}" for warning in warnings)
            + ("\n" if warnings else ""),
            encoding="utf-8",
        )
        (staging / "run-eclab.sh").write_text(
            _launcher(topology_path.name, offline=offline), encoding="utf-8"
        )
        os.chmod(staging / "run-eclab.sh", 0o755)
        temporary_archive = Path(work) / archive.name
        with tarfile.open(temporary_archive, "w:gz") as tar:
            tar.add(staging, arcname=root_name, recursive=True)
        track_archive(workspace, source_root, archive)
        temporary_archive.replace(archive)
    return True


def _default_archive(topology_path: Path) -> Path:
    root = topology_path.parent.resolve()
    name = root.name or "frozen-lab"
    return root / f"{name}.tar.gz"


def _archive_root_name(archive: Path) -> str:
    name = archive.name.removesuffix(".tar.gz").removesuffix(".tgz")
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-") or "frozen-lab"


def _relative_to(root: Path, path: Path) -> Path | None:
    try:
        return path.relative_to(root)
    except ValueError:
        return None


def _confirm_overwrite(archive: Path) -> bool:
    """Ask an interactive caller whether to replace an existing archive."""
    if not sys.stdin.isatty():
        raise FreezeError(
            f"a file already exists at the output path: {archive}; "
            "remove it or rerun from an interactive terminal to overwrite it"
        )
    while True:
        try:
            answer = input(
                f"A file already exists at the output path: {archive}. Overwrite it (y/n)? "
            )
        except EOFError:
            return False
        normalized = answer.strip().lower()
        if normalized in {"y", "yes"}:
            return True
        if normalized in {"", "n", "no"}:
            return False


def _containerlab_runtime_directory(
    topology: dict[str, Any], topology_path: Path
) -> Path:
    """Return Containerlab's topology-local runtime directory name."""
    name = topology.get("name")
    if isinstance(name, str) and name.strip():
        lab_name = name.strip()
    else:
        lab_name = topology_path.name
        for suffix in (".clab.yml", ".clab.yaml", ".yml", ".yaml"):
            if lab_name.endswith(suffix):
                lab_name = lab_name.removesuffix(suffix)
                break
    return Path(f"clab-{lab_name}")


def _state_prefix(application_name: str) -> str:
    """Normalize the active application's name for state-directory naming only.

    Unlike topology labels (fixed to `_LABEL_PREFIX`), the local state
    directory intentionally keeps deriving from application metadata, so
    every edition's state converges on the same directory as long as they
    share the same short_product_name.
    """
    prefix = _NON_ALPHANUMERIC.sub("_", application_name.upper()).strip("_")
    if not prefix:
        raise FreezeError(f"cannot derive a state directory from {application_name!r}")
    return prefix


def _state_directory(application_name: str) -> str:
    return f".{_state_prefix(application_name).lower()}"


def _ignore_patterns(root: Path, application_name: str = "eclab") -> tuple[str, ...]:
    ignore = root / f".{_state_prefix(application_name).lower()}-freezeignore"
    if not ignore.is_file():
        return ()
    return tuple(
        line.strip()
        for line in ignore.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def _ignored(
    relative: Path, patterns: Iterable[str], excluded: frozenset[Path]
) -> bool:
    text = relative.as_posix()
    return (
        relative in excluded
        or relative.name in _BUILTIN_IGNORES
        or _is_generated_topology(relative)
        or any(
            fnmatch.fnmatch(text, pattern) or fnmatch.fnmatch(relative.name, pattern)
            for pattern in patterns
        )
    )


def _is_generated_topology(relative: Path) -> bool:
    """Return whether a path is a lab-writer topology beside its source.

    These files are a deploy-time rendering, not authored lab input.  Keeping
    one in a portable archive would give the recipient two topology copies
    which can diverge, and the hidden copy can also make topology discovery
    ambiguous after defrost.
    """
    return (
        relative.parent == Path(".")
        and relative.name.startswith(WRITER_TEMP_PREFIX)
        and relative.name.endswith((".clab.yml", ".clab.yaml"))
    )


def _reject_external_symlinks(
    root: Path, patterns: tuple[str, ...], excluded: frozenset[Path]
) -> None:
    for directory, directories, files in os.walk(root, topdown=True, followlinks=False):
        base = Path(directory)
        retained_directories: list[str] = []
        for name in directories:
            path = base / name
            relative = path.relative_to(root)
            if _ignored(relative, patterns, excluded):
                continue
            _reject_external_symlink(path, relative, root)
            retained_directories.append(name)
        directories[:] = retained_directories
        for name in files:
            path = base / name
            relative = path.relative_to(root)
            if not _ignored(relative, patterns, excluded):
                _reject_external_symlink(path, relative, root)


def _reject_external_symlink(path: Path, relative: Path, root: Path) -> None:
    if path.is_symlink() and not path.resolve().is_relative_to(root):
        raise FreezeError(f"symlink escapes the lab directory: {relative}")


def _copy_source(
    root: Path,
    destination: Path,
    patterns: tuple[str, ...],
    excluded: frozenset[Path],
) -> list[str]:
    warnings: list[str] = []

    def ignore(directory: str, names: list[str]) -> set[str]:
        base = Path(directory)
        ignored_names: set[str] = set()
        for name in names:
            relative = (base / name).relative_to(root)
            if _ignored(relative, patterns, excluded):
                ignored_names.add(name)
            elif (base / name).is_file() and name.lower().endswith(_LICENSE_SUFFIXES):
                ignored_names.add(name)
                warnings.append(f"excluded possible license file: {relative}")
            elif (base / name).is_file() and name.lower().endswith(_PRIVATE_SUFFIXES):
                ignored_names.add(name)
                warnings.append(f"excluded owner-private environment file: {relative}")
        return ignored_names

    shutil.copytree(root, destination, symlinks=True, ignore=ignore)
    return warnings


def _prune_empty_directories(root: Path) -> None:
    """Remove empty source directories left after exclusions from staging."""
    for candidate in sorted(
        root.rglob("*"), key=lambda path: len(path.parts), reverse=True
    ):
        if candidate.is_dir() and not candidate.is_symlink():
            try:
                candidate.rmdir()
            except OSError:
                pass


def _freeze_topology(
    copied_path: Path,
    source_root: Path,
    staging_root: Path,
    packages: list[tuple[str, str]],
    warnings: list[str],
    *,
    offline: bool = False,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    current_environment = os.environ if environment is None else environment
    copied = parse_topology_yaml(copied_path.read_text(encoding="utf-8"))
    if not isinstance(copied, dict):
        raise FreezeError("topology must contain a YAML mapping")
    topology = copied.get("topology")
    nodes = topology.get("nodes") if isinstance(topology, dict) else None
    if not isinstance(nodes, dict):
        raise FreezeError("topology.nodes is required")
    for declaration in topology_declarations(copied):
        definition = copied
        for part in declaration.origin.path:
            definition = definition[part]
        if "license" in definition:
            definition["license"] = f"__{_LABEL_PREFIX}_LICENSE_PROMPT__"
        environment = definition.get("env")
        if isinstance(environment, dict):
            for key in tuple(environment):
                if isinstance(key, str) and key.endswith("_LIC_CLAMP"):
                    environment.pop(key)
    if offline:
        _remove_offline_vrnetlab_inputs(
            copied, copied_path, staging_root, warnings, current_environment
        )
    else:
        _copy_external_vrnetlab_inputs(
            copied,
            copied_path,
            source_root,
            staging_root,
            warnings,
            current_environment,
        )
    freeze_metadata: dict[str, Any] = {
        "format": 2,
        "application": "engulf-clab",
        "packages": [{"name": name, "version": version} for name, version in packages],
        "tools": _tool_provenance(current_environment),
        "licenses": "prompt",
        "offline": offline,
    }
    copied[_FREEZE_KEY] = freeze_metadata
    copied_path.write_text(yaml.safe_dump(copied, sort_keys=False), encoding="utf-8")
    return freeze_metadata


def _bundle_offline_runtime(staging: Path) -> None:
    """Copy the active, installed eclab virtual environment into the archive."""
    source = Path(sys.prefix).resolve()
    if sys.prefix == sys.base_prefix or not (source / "bin" / "eclab").is_file():
        raise FreezeError(
            "--offline requires freeze to run from a virtual environment containing eclab"
        )
    destination = staging / ".eclab-venv"
    shutil.copytree(
        source,
        destination,
        symlinks=False,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    if (
        not (destination / "bin" / "python").is_file()
        or not (destination / "bin" / "eclab").is_file()
    ):
        raise FreezeError(
            "could not create a complete offline eclab virtual environment"
        )


def _executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _managed_tool_path(state: StateStore | None, name: str) -> Path | None:
    if state is None:
        return None
    try:
        return state.path(name)
    except (AttributeError, OSError):
        return None


def _containerlab_binary(
    user_state: StateStore | None = None,
    environment: Mapping[str, str] | None = None,
) -> Path:
    current_environment = os.environ if environment is None else environment
    candidates: list[Path] = []
    if configured := current_environment.get("CONTAINERLAB_BIN", "").strip():
        candidates.append(Path(configured).expanduser())
    if configured := current_environment.get("CONTAINERLAB_DIR", "").strip():
        checkout = Path(configured).expanduser()
        candidates.extend(
            (checkout / "bin" / "containerlab", checkout / "containerlab")
        )
    if discovered := shutil.which("containerlab"):
        candidates.append(Path(discovered))
    if managed := _managed_tool_path(user_state, "containerlab"):
        candidates.extend((managed / "bin" / "containerlab", managed / "containerlab"))
    for candidate in candidates:
        resolved = candidate.resolve()
        if _executable(resolved):
            return resolved
    raise FreezeError(
        "--offline requires an executable Containerlab in CONTAINERLAB_BIN, "
        "CONTAINERLAB_DIR, or PATH"
    )


def _bundle_offline_containerlab(
    staging: Path,
    user_state: StateStore | None = None,
    environment: Mapping[str, str] | None = None,
) -> None:
    source = _containerlab_binary(user_state, environment)
    destination = staging / "tools" / "containerlab" / "bin" / "containerlab"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    os.chmod(destination, source.stat().st_mode | 0o111)


def _remove_offline_vrnetlab_inputs(
    topology: dict[str, Any],
    topology_path: Path,
    staging: Path,
    warnings: list[str],
    environment: Mapping[str, str] | None = None,
) -> None:
    current_environment = os.environ if environment is None else environment
    """Exclude vendor VM inputs while retaining vrnetlab builder selections."""
    try:
        requests = list(
            build_requests_from_topology(topology_path, topology, current_environment)
        )
    except Exception:  # noqa: BLE001 - unresolved recipient-owned inputs are expected.
        requests = []
    for request in requests:
        source = request.source
        if source is None or not source.is_relative_to(staging):
            continue
        if source.is_file() or source.is_symlink():
            source.unlink()
            warnings.append(
                f"excluded recipient-selected vrnetlab image input: {source.name}"
            )

    document = topology.get("topology")
    nodes = document.get("nodes") if isinstance(document, dict) else None
    if not isinstance(nodes, dict):
        return
    for declaration in topology_declarations(topology):
        owner: Any = topology
        for part in declaration.origin.path:
            owner = owner[part]
        environment = owner.get("env") if isinstance(owner, dict) else None
        if not isinstance(environment, dict):
            continue
        for name in tuple(environment):
            if isinstance(name, str) and name.endswith("_VRNETLAB_IMG_PATH"):
                environment.pop(name)


def _vrnetlab_checkout(
    user_state: StateStore | None = None,
    environment: Mapping[str, str] | None = None,
) -> Path:
    current_environment = os.environ if environment is None else environment
    configured = current_environment.get("VRNETLAB_DIR", "").strip()
    candidates = [Path(configured).expanduser()] if configured else []
    if managed := _managed_tool_path(user_state, "vrnetlab"):
        candidates.append(managed)
    for candidate in candidates:
        checkout = candidate.resolve()
        if (checkout / "common" / "vrnetlab.py").is_file():
            return checkout
    raise FreezeError(
        "--offline requires a valid VRNETLAB_DIR or managed vrnetlab checkout "
        "for a vrnetlab-enabled topology"
    )


def _bundle_offline_vrnetlab(
    staging: Path,
    user_state: StateStore | None = None,
    environment: Mapping[str, str] | None = None,
) -> None:
    source = _vrnetlab_checkout(user_state, environment)
    destination = staging / "tools" / "vrnetlab"
    shutil.copytree(
        source,
        destination,
        symlinks=False,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "*.pyo"),
    )
    if not (destination / "common" / "vrnetlab.py").is_file():
        raise FreezeError("could not create a complete offline vrnetlab checkout")


def _offline_image_references(
    topology: dict[str, Any], environment: Mapping[str, str] | None = None
) -> tuple[str, ...]:
    current_environment = os.environ if environment is None else environment
    document = topology.get("topology")
    nodes = document.get("nodes") if isinstance(document, dict) else None
    if not isinstance(nodes, dict):
        return ()
    references: set[str] = set()
    try:
        resolved_nodes = effective_nodes(topology)
    except TopologyError as error:
        raise FreezeError(f"could not resolve inherited topology settings: {error}") from error
    for effective in resolved_nodes:
        name = effective.name
        node = nodes.get(name)
        if node is None:
            node = nodes[name] = {}
        if not isinstance(node, dict):
            continue
        environment = effective.data.get("env")
        if isinstance(environment, Mapping) and any(
            isinstance(key, str) and key.endswith("_VRNETLAB_TYPE")
            for key in environment
        ):
            continue
        image = effective.data.get("image")
        if image is None:
            continue
        if not isinstance(image, str) or not image.strip():
            raise FreezeError(f"node {name} has an invalid image reference")
        try:
            resolved = resolve_image_expression(image.strip(), current_environment)
        except Exception as error:
            raise FreezeError(
                f"node {name} image cannot be resolved for offline use: {image}"
            ) from error
        node["image"] = resolved
        references.add(resolved)
    return tuple(sorted(references))


def _bundle_offline_images(
    topology: dict[str, Any],
    staging: Path,
    environment: Mapping[str, str] | None = None,
) -> None:
    references = _offline_image_references(topology, environment)
    if not references:
        return
    if shutil.which("docker") is None:
        raise FreezeError("--offline requires docker to package topology images")
    missing: list[str] = []
    for reference in references:
        result = subprocess.run(
            ["docker", "image", "inspect", reference],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode:
            missing.append(reference)
    if missing:
        raise FreezeError(
            "--offline requires all topology images to exist locally; deploy or pull first: "
            + ", ".join(missing)
        )
    image_dir = staging / "tools" / "docker"
    image_dir.mkdir(parents=True, exist_ok=True)
    archive = image_dir / "images.tar"
    try:
        subprocess.run(
            ["docker", "image", "save", "--output", str(archive), *references],
            check=True,
        )
    except subprocess.CalledProcessError as error:
        raise FreezeError("docker could not export the topology images") from error
    (image_dir / "images.txt").write_text(
        "\n".join(references) + "\n", encoding="utf-8"
    )


def _copy_external_vrnetlab_inputs(
    topology: dict[str, Any],
    path: Path,
    source_root: Path,
    staging: Path,
    warnings: list[str],
    environment: Mapping[str, str] | None = None,
) -> None:
    current_environment = os.environ if environment is None else environment
    try:
        requests = build_requests_from_topology(path, topology, current_environment)
    except Exception as error:  # noqa: BLE001 - a best-effort freeze retains an unresolved source.
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
        if node is None:
            node = nodes[request.node_name] = {}
        if isinstance(node, dict):
            node_environment = node.get("env")
            if node_environment is None:
                node_environment = node["env"] = {}
            if isinstance(node_environment, dict):
                node_environment[vrnetlab_image_path_env()] = str(
                    target.relative_to(staging)
                )
        warnings.append(
            f"copied external vrnetlab input for {request.node_name}: sha256={_sha256(target)}"
        )


def _tool_provenance(environment: Mapping[str, str]) -> dict[str, object]:
    return {
        "containerlab": _git_provenance(environment.get("CONTAINERLAB_DIR")),
        "vrnetlab": _git_provenance(environment.get("VRNETLAB_DIR")),
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
    result = subprocess.run(
        ["git", "-C", str(root), *args], text=True, capture_output=True, check=False
    )
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


def _download_wheels(
    staging: Path, packages: list[tuple[str, str]], warnings: list[str]
) -> None:
    wheelhouse = staging / "wheelhouse"
    wheelhouse.mkdir()
    _seed_installed_wheels(packages, wheelhouse, warnings)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "download",
            "--dest",
            str(wheelhouse),
            "--find-links",
            str(wheelhouse),
            "-r",
            str(staging / "requirements.freeze.txt"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        warnings.append(
            "could not obtain a complete wheelhouse; launcher will fall back to its package index"
        )
    if not any(wheelhouse.iterdir()):
        wheelhouse.rmdir()


def _seed_installed_wheels(
    packages: Iterable[tuple[str, str]], wheelhouse: Path, warnings: list[str]
) -> None:
    """Copy exact file-installed wheels before asking an index for dependencies."""
    for name, _version in packages:
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            continue
        source = _installed_wheel_path(distribution)
        if source is None:
            continue
        try:
            shutil.copy2(source, wheelhouse / source.name)
        except OSError as error:
            warnings.append(f"could not copy installed wheel for {name}: {error}")


def _installed_wheel_path(distribution: importlib.metadata.Distribution) -> Path | None:
    """Return a verified local wheel recorded by PEP 610, when one exists."""
    try:
        content = distribution.read_text("direct_url.json")
        record: object = json.loads(content) if content is not None else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(record, dict) or not isinstance(record.get("url"), str):
        return None
    parsed = urlsplit(record["url"])
    if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
        return None
    source = Path(unquote(parsed.path))
    if not source.is_file() or source.suffix.lower() != ".whl":
        return None
    archive = record.get("archive_info")
    expected_hash = archive.get("hash") if isinstance(archive, dict) else None
    if (
        isinstance(expected_hash, str)
        and expected_hash.startswith("sha256=")
        and _sha256(source) != expected_hash.removeprefix("sha256=")
    ):
        return None
    return source


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _launcher(topology_name: str, *, offline: bool = False) -> str:
    if offline:
        return f"""#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${{BASH_SOURCE[0]}}")" && pwd)"
runtime="$root/.eclab-venv"
containerlab="$root/tools/containerlab/bin/containerlab"
vrnetlab="$root/tools/vrnetlab"
images="$root/tools/docker/images.tar"
image_list="$root/tools/docker/images.txt"
if [[ ! -x "$runtime/bin/python" || ! -f "$runtime/bin/eclab" ]]; then
    echo "offline eclab runtime is incomplete" >&2
    exit 1
fi
if [[ ! -x "$containerlab" ]]; then
    echo "offline Containerlab executable is missing" >&2
    exit 1
fi
export CONTAINERLAB_BIN="$containerlab"
export CONTAINERLAB_UPDATE=0
export PATH="$(dirname -- "$containerlab"):$PATH"
if [[ -d "$vrnetlab" ]]; then
    export VRNETLAB_DIR="$vrnetlab"
    export VRNETLAB_UPDATE=0
fi
if [[ -f "$image_list" ]]; then
    missing_image=0
    while IFS= read -r image; do
        [[ -z "$image" ]] && continue
        if ! docker image inspect "$image" >/dev/null 2>&1; then
            missing_image=1
            break
        fi
    done < "$image_list"
    if [[ "$missing_image" -eq 1 ]]; then
        docker image load --input "$images"
    fi
fi
if [[ $# -eq 0 ]]; then set -- deploy -t {topology_name!s}; fi
exec "$runtime/bin/python" "$runtime/bin/eclab" "$@"
"""
    return f"""#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${{BASH_SOURCE[0]}}")" && pwd)"
requirements="$root/requirements.freeze.txt"
wheelhouse="$root/wheelhouse"
source "$root/.eclab-freeze.env"
pip_links=()
if [[ -d "$wheelhouse" ]]; then
    pip_links=(--find-links "$wheelhouse")
fi
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
        python3 -m pip install --user "${{pip_links[@]}}" -r "$requirements"
        runner="$(command -v eclab)"
    fi
fi
if [[ -z "$runner" ]]; then
    venv="$root/.eclab-venv"
    if [[ ! -x "$venv/bin/eclab" ]]; then
        python3 -m venv "$venv"
        "$venv/bin/python" -m pip install "${{pip_links[@]}}" -r "$requirements"
    fi
    runner="$venv/bin/eclab"
fi
if [[ $# -eq 0 ]]; then set -- deploy -t {topology_name!s}; fi
exec "$runner" "$@"
"""
