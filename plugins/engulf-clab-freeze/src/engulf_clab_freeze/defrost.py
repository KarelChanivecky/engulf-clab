"""Implementation of the ``eclab defrost`` control command."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

import yaml  # type: ignore[import-untyped]
from engulf_api import PluginLogger
from engulf_clab_freeze_api import DefrostContext, discover_contributors
from engulf_clab_freeze_api import FreezeError as ContributorError
from engulf_clab_lab_parser import effective_nodes, parse_topology_yaml
from engulf_clab_lab_parser.session import WRITER_TEMP_PREFIX
from engulf_clab_vrnetlab_build.config import (
    build_requests_from_topology,
    resolve_image_expression,
)

from .command import _FREEZE_KEY, _LABEL_PREFIX, _archive_root_name, _state_prefix

# Keys the recipient's plugins read back. They use the fixed `ECLAB` prefix for
# exactly the reason freeze writes it: engulf-clab-license-pool and
# engulf-clab-image-archive keep these names portable across editions.
_LICENSE_PROMPT = f"__{_LABEL_PREFIX}_LICENSE_PROMPT__"
_LICENSE_ENV = f"{_LABEL_PREFIX}_LICENSE"
_IMAGE_ARCHIVE_ENV = f"{_LABEL_PREFIX}_IMAGE_ARCHIVE"
# Mirrors the lab parser's private topology globs. Defrost selects inside an
# extracted archive, so it cannot reuse that module's invocation-directory scan.
_TOPOLOGY_PATTERNS = (
    "*.clab.yml",
    "*.clab.yaml",
    "clab.yml",
    "clab.yaml",
    "topology.yml",
    "topology.yaml",
)
# `docker load` reads an uncompressed tar or a gzip, bzip2, or xz compressed one;
# engulf-clab-image-archive accepts exactly these suffixes.
_IMAGE_ARCHIVE_SUFFIXES = (
    ".tar",
    ".tar.gz",
    ".tgz",
    ".tar.bz2",
    ".tbz2",
    ".tar.xz",
    ".txz",
)
_ARCHIVE_SUFFIXES = (".tar.gz", ".tgz")
_UNSCANNED = frozenset({".eclab-venv", ".venv", ".git", "__pycache__", "wheelhouse"})
_REQUIREMENT = re.compile(r"([A-Za-z0-9_.-]+)==([^\s]+)")
_FREEZE_APPLICATION = "engulf-clab"
_SUPPORTED_FORMATS = frozenset((1, 2))
_RECORD_VERSION = 1


class DefrostError(RuntimeError):
    """A frozen archive cannot safely become a runnable lab directory."""


def main(
    argv: list[str] | None = None,
    *,
    program: str = "eclab defrost",
    application_name: str = "eclab",
    logger: PluginLogger | None = None,
    environment: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    user_state: Path | None = None,
) -> int:
    """Run the optional defrost command against one frozen archive."""
    try:
        contributors = discover_contributors()
        parser = _parser(program, contributors)
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
    base = Path.cwd() if cwd is None else cwd
    try:
        archive = _resolve(base, arguments.archive)
        defrost(
            archive,
            destination(archive, arguments.into, base),
            licenses=_license_answers(arguments.license or []),
            prompt_licenses=not arguments.no_license_prompt,
            prepare_runtime=not arguments.no_runtime,
            select_images=not arguments.no_images,
            load_images=arguments.load_images,
            force=arguments.force,
            application_name=application_name,
            logger=logger,
            environment=environment,
            contributors=contributors,
            contributor_arguments=arguments,
            user_state=user_state,
        )
    except (
        DefrostError,
        ContributorError,
        OSError,
        tarfile.TarError,
        yaml.YAMLError,
    ) as error:
        if logger is None:
            print(f"{program}: {error}", file=sys.stderr)
        else:
            logger.error("%s: %s", program, error)
        return 1
    return 0


def _parser(
    program: str, contributors: tuple[Any, ...] = ()
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=program)
    parser.add_argument(
        "archive",
        metavar="ARCHIVE",
        help="frozen .tar.gz or .tgz archive to expand",
    )
    parser.add_argument(
        "--into",
        metavar="DIRECTORY",
        help="destination lab directory (default: ./<archive-name-without-suffix>)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace a directory a previous defrost created at the destination",
    )
    parser.add_argument(
        "--license",
        action="append",
        metavar="NODE=VALUE",
        help="answer a frozen license prompt; VALUE alone answers every prompted node",
    )
    parser.add_argument(
        "--no-license-prompt",
        action="store_true",
        help="keep frozen license markers instead of asking for paths",
    )
    parser.add_argument(
        "--no-runtime",
        action="store_true",
        help="skip runtime preparation and leave it to run-eclab.sh",
    )
    parser.add_argument(
        "--no-images",
        action="store_true",
        help="skip bundled Docker image archive selection",
    )
    parser.add_argument(
        "--load-images",
        action="store_true",
        help="load matched bundled image archives into Docker now instead of at deploy",
    )
    for contributor in contributors:
        contributor.add_defrost_arguments(parser)
    return parser


def destination(archive: Path, requested: str | None, base: Path) -> Path:
    """Return the lab directory one archive expands into.

    The default name comes from the archive filename, exactly as freeze derives
    the archive's own single root, so it is known without reading the archive.
    """
    if requested:
        return _resolve(base, requested)
    return _resolve(base, _archive_root_name(archive))


def defrost(
    archive: Path,
    into: Path,
    *,
    licenses: Mapping[str, str] | None = None,
    prompt_licenses: bool = True,
    ask: Callable[[str], str | None] | None = None,
    prepare_runtime: bool = True,
    select_images: bool = True,
    load_images: bool = False,
    force: bool = False,
    application_name: str = "eclab",
    logger: PluginLogger | None = None,
    environment: Mapping[str, str] | None = None,
    contributors: tuple[Any, ...] = (),
    contributor_arguments: argparse.Namespace | None = None,
    user_state: Path | None = None,
) -> bool:
    """Expand one frozen archive into an atomically published, runnable lab."""
    archive = archive.expanduser().resolve()
    into = into.expanduser().resolve()
    current_environment = os.environ if environment is None else environment
    answers = dict(licenses or {})
    if not archive.name.lower().endswith(_ARCHIVE_SUFFIXES):
        raise DefrostError("archive must end in .tar.gz or .tgz")
    if archive.is_symlink() or not archive.is_file():
        raise DefrostError(f"archive is not a regular file: {archive}")
    if not into.parent.is_dir():
        raise DefrostError(f"destination parent does not exist: {into.parent}")
    record_name = f".{_state_prefix(application_name).lower()}-defrost.json"
    replacing = _check_destination(into, record_name, force=force)
    notes: list[str] = []
    with tempfile.TemporaryDirectory(prefix=".eclab-defrost-", dir=into.parent) as work:
        temporary_root = Path(work)
        root = _extract(archive, temporary_root / "staging")
        topology_path = _archive_topology(root)
        document = _load_document(topology_path)
        metadata = _freeze_metadata(document, notes)
        offline = bool(metadata.get("offline"))
        _restore_executables(root, notes, offline=offline)
        if prepare_runtime:
            _verify_runtime(root, offline=offline)
        selected: dict[str, str] = {}
        if select_images:
            selected = _select_image_archives(
                root, topology_path, document, notes, environment=current_environment
            )
        _resolve_licenses(
            document,
            answers,
            notes,
            prompt=prompt_licenses,
            ask=ask,
            environment=current_environment,
        )
        _report_vrnetlab_inputs(
            topology_path, document, notes, environment=current_environment
        )
        _write_document(topology_path, document)
        contribution_metadata = metadata.get("contributors", {})
        if not isinstance(contribution_metadata, dict):
            raise DefrostError("freeze contributor metadata must be a mapping")
        installed = {item.contributor_id: item for item in contributors}
        for contributor_id, contribution in contribution_metadata.items():
            contributor = installed.get(contributor_id)
            if contributor is None:
                raise DefrostError(
                    f"archive requires missing freeze contributor {contributor_id!r}"
                )
            if not isinstance(contribution, dict):
                raise DefrostError(
                    f"invalid metadata for contributor {contributor_id!r}"
                )
            contributor.defrost(
                DefrostContext(
                    topology=topology_path,
                    staging_root=root,
                    destination=into,
                    metadata=contribution,
                    arguments=contributor_arguments or argparse.Namespace(),
                    environment=current_environment,
                    user_state=user_state,
                )
            )
        record = root / record_name
        _write_record(record, archive, topology_path.relative_to(root), metadata, notes)
        _publish(root, into, temporary_root, replacing=replacing)
    if prepare_runtime:
        _prepare_runtime(into, notes, offline=offline)
    if load_images:
        _load_images(into, selected, notes)
    _write_record(
        into / record_name, archive, topology_path.relative_to(root), metadata, notes
    )
    for note in notes:
        _log(logger, note)
    _log(logger, f"expanded {archive.name} into {into}")
    return True


def _resolve(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else base / path).resolve()


def _license_answers(values: list[str]) -> dict[str, str]:
    """Split ``NODE=VALUE`` answers from one answer for every prompted node.

    A value without ``=``, and any value whose left side looks like a path
    rather than a node name, answers every node. Node names never contain a
    path separator, so an answer such as ``/pools/site=a`` stays one path.
    """
    answers: dict[str, str] = {}
    for value in values:
        node, separator, remainder = value.partition("=")
        if separator and node and "/" not in node and not node.startswith("$"):
            answers[node] = remainder
        else:
            answers["*"] = value
    return answers


def _check_destination(into: Path, record_name: str, *, force: bool) -> bool:
    """Return whether publication may replace an existing recorded destination."""
    if not into.exists() and not into.is_symlink():
        return False
    if into.is_symlink() or not into.is_dir():
        raise DefrostError(f"destination exists and is not a directory: {into}")
    if not force:
        raise DefrostError(
            f"destination already exists: {into}; pass --force to replace a previous defrost"
        )
    if not (into / record_name).is_file():
        raise DefrostError(f"refusing to replace an unrecognized directory: {into}")
    return True


def _extract(archive: Path, staging: Path) -> Path:
    """Extract one archive under a single lab root, rejecting escaping members."""
    staging.mkdir(parents=True)
    with tarfile.open(archive, "r:*") as tar:
        roots: set[str] = set()
        for member in tar.getmembers():
            name = PurePosixPath(member.name)
            parts = tuple(part for part in name.parts if part != ".")
            if not parts:
                continue
            if name.is_absolute() or ".." in parts:
                raise DefrostError(f"archive member escapes its root: {member.name}")
            roots.add(parts[0])
        if len(roots) != 1:
            raise DefrostError("archive must contain exactly one lab directory")
        tar.extractall(staging, filter="data")
    return staging / roots.pop()


def _archive_topology(root: Path) -> Path:
    """Return the one topology freeze stamped, which is never ambiguous."""
    matches: list[Path] = []
    for pattern in _TOPOLOGY_PATTERNS:
        for path in sorted(root.glob(pattern)):
            if (
                path.is_file()
                and not path.name.startswith(WRITER_TEMP_PREFIX)
                and path not in matches
            ):
                matches.append(path)
    frozen = [path for path in matches if _carries_freeze_key(path)]
    if len(frozen) == 1:
        return frozen[0]
    if not frozen:
        raise DefrostError(
            f"no archive topology carries {_FREEZE_KEY}; this is not a frozen lab archive"
        )
    raise DefrostError(f"archive has several topologies carrying {_FREEZE_KEY}")


def _carries_freeze_key(path: Path) -> bool:
    try:
        document = parse_topology_yaml(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return False
    return isinstance(document, dict) and _FREEZE_KEY in document


def _load_document(path: Path) -> dict[str, Any]:
    try:
        document = parse_topology_yaml(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise DefrostError(f"could not read the frozen topology: {error}") from error
    if not isinstance(document, dict):
        raise DefrostError("topology must contain a YAML mapping")
    return document


def _write_document(path: Path, document: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def _freeze_metadata(document: dict[str, Any], notes: list[str]) -> dict[str, Any]:
    """Remove and validate the freeze metadata the recipient must not deploy."""
    metadata = document.pop(_FREEZE_KEY, None)
    if metadata is None:
        raise DefrostError(
            f"the topology has no {_FREEZE_KEY} metadata; it was not produced by freeze"
        )
    if not isinstance(metadata, dict):
        raise DefrostError(f"{_FREEZE_KEY} metadata must be a YAML mapping")
    if metadata.get("format") not in _SUPPORTED_FORMATS:
        raise DefrostError(
            f"unsupported freeze format: {metadata.get('format')!r}; upgrade this plugin"
        )
    if metadata.get("application") != _FREEZE_APPLICATION:
        notes.append(
            f"archive was frozen by an unrecognized application: {metadata.get('application')!r}"
        )
    return metadata


def _nodes(document: dict[str, Any]) -> dict[str, Any]:
    topology = document.get("topology")
    nodes = topology.get("nodes") if isinstance(topology, dict) else None
    if not isinstance(nodes, dict):
        raise DefrostError("topology.nodes is required")
    return nodes


def _restore_executables(root: Path, notes: list[str], *, offline: bool) -> None:
    """Restore the launcher and bundled tool permissions the recipient runs."""
    launcher = root / "run-eclab.sh"
    if launcher.is_file():
        launcher.chmod(0o755)
    else:
        notes.append("archive has no run-eclab.sh launcher")
    if not offline:
        return
    for relative in (
        Path("tools/containerlab/bin/containerlab"),
        Path(".eclab-venv/bin/python"),
        Path(".eclab-venv/bin/eclab"),
    ):
        path = root / relative
        if path.is_file():
            path.chmod(path.stat().st_mode | 0o111)


def _verify_runtime(root: Path, *, offline: bool) -> None:
    """Fail before publishing when the archive cannot produce a usable runtime."""
    if not offline:
        if not (root / "requirements.freeze.txt").is_file():
            raise DefrostError(
                "archive has no requirements.freeze.txt; it is not a complete freeze"
            )
        return
    venv = root / ".eclab-venv"
    if (
        not (venv / "bin" / "python").is_file()
        or not (venv / "bin" / "eclab").is_file()
    ):
        raise DefrostError("offline archive has no complete .eclab-venv runtime")
    if not (root / "tools" / "containerlab" / "bin" / "containerlab").is_file():
        raise DefrostError("offline archive has no bundled Containerlab executable")
    vrnetlab = root / "tools" / "vrnetlab"
    if vrnetlab.is_dir() and not (vrnetlab / "common" / "vrnetlab.py").is_file():
        raise DefrostError("bundled vrnetlab checkout is incomplete")


def _prepare_runtime(into: Path, notes: list[str], *, offline: bool) -> None:
    """Make the published lab runnable from its final location.

    Runs after publication so every absolute path a virtual environment records
    is the one the recipient actually runs, and so a package-index failure
    cannot discard an otherwise complete lab.
    """
    venv = into / ".eclab-venv"
    if offline:
        _relocate_virtual_environment(venv)
        notes.append("bundled offline runtime is ready")
        return
    requirements = into / "requirements.freeze.txt"
    if _installed_packages_match(requirements):
        notes.append("this installation already matches the frozen package lock")
        return
    if (venv / "bin" / "eclab").is_file():
        notes.append("reusing the lab runtime already present in .eclab-venv")
        return
    _create_virtual_environment(venv, requirements, into / "wheelhouse", notes)


def _relocate_virtual_environment(venv: Path) -> None:
    """Repoint console-script shebangs at the extracted interpreter."""
    binaries = venv / "bin"
    interpreter = f"#!{binaries / 'python'}".encode()
    if not binaries.is_dir():
        return
    for entry in sorted(binaries.iterdir()):
        if entry.is_symlink() or not entry.is_file():
            continue
        try:
            content = entry.read_bytes()
        except OSError:
            continue
        shebang, separator, remainder = content.partition(b"\n")
        if not shebang.startswith(b"#!") or b"python" not in shebang or not separator:
            continue
        entry.write_bytes(interpreter + separator + remainder)


def _installed_packages_match(requirements: Path) -> bool:
    """Return whether this runtime already has every frozen package version.

    Mirrors the launcher's ``--eclab-freeze-compatible`` check in process, since
    defrost already runs inside the installed executable.
    """
    try:
        lines = requirements.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return False
    for line in lines:
        match = _REQUIREMENT.fullmatch(line.strip())
        if match is None:
            continue
        try:
            installed = importlib.metadata.version(match.group(1))
        except importlib.metadata.PackageNotFoundError:
            return False
        if installed != match.group(2):
            return False
    return True


def _create_virtual_environment(
    venv: Path, requirements: Path, wheelhouse: Path, notes: list[str]
) -> None:
    creation = subprocess.run(
        [sys.executable, "-m", "venv", str(venv)],
        capture_output=True,
        text=True,
        check=False,
    )
    if creation.returncode:
        shutil.rmtree(venv, ignore_errors=True)
        notes.append("could not create .eclab-venv; run-eclab.sh will prepare it")
        return
    command = [str(venv / "bin" / "python"), "-m", "pip", "install"]
    if wheelhouse.is_dir():
        command.extend(("--find-links", str(wheelhouse)))
    command.extend(("-r", str(requirements)))
    installation = subprocess.run(command, capture_output=True, text=True, check=False)
    if installation.returncode:
        shutil.rmtree(venv, ignore_errors=True)
        notes.append(
            "could not install the frozen packages; run-eclab.sh will retry at first use"
        )
        return
    notes.append("installed the frozen packages into .eclab-venv")


def _select_image_archives(
    root: Path,
    topology_path: Path,
    document: dict[str, Any],
    notes: list[str],
    *,
    environment: Mapping[str, str],
) -> dict[str, str]:
    """Point nodes at bundled image archives so deploy loads instead of pulls.

    Only an archive that actually carries the node's exact image reference is
    selected, because engulf-clab-image-archive treats a declared archive as the
    node's image source and never falls back to a registry pull.
    """
    selected: dict[str, str] = {}
    available = _bundled_images(root)
    if not available:
        return selected
    nodes = _nodes(document)
    for effective in effective_nodes(document):
        name = effective.name
        node = nodes[name]
        if node is None:
            node = nodes[name] = {}
        declared = effective.data.get("env")
        if isinstance(declared, Mapping):
            if _IMAGE_ARCHIVE_ENV in declared:
                continue
            if any(
                isinstance(key, str) and key.endswith("_VRNETLAB_TYPE")
                for key in declared
            ):
                continue
        reference = _resolved_image(effective.data.get("image"), environment)
        if reference is None:
            continue
        archive = available.get(_canonical_reference(reference))
        if archive is None:
            continue
        node_environment = node.setdefault("env", {})
        if not isinstance(node_environment, dict):
            continue
        relative = os.path.relpath(archive, topology_path.parent)
        node_environment[_IMAGE_ARCHIVE_ENV] = PurePosixPath(relative).as_posix()
        selected[reference] = archive.relative_to(root).as_posix()
        notes.append(f"node {name} loads {reference} from the bundled {relative}")
    return selected


def _resolved_image(image: object, environment: Mapping[str, str]) -> str | None:
    """Return one node's literal image tag, or nothing when it stays unresolved."""
    if not isinstance(image, str) or not image.strip():
        return None
    try:
        return resolve_image_expression(image.strip(), environment)
    except Exception:  # noqa: BLE001 - a recipient-owned tag is not defrost's to resolve.
        return None


def _bundled_images(root: Path) -> dict[str, Path]:
    """Map every image reference an archive in the lab can supply to that archive."""
    available: dict[str, Path] = {}
    listing = root / "tools" / "docker" / "images.txt"
    bundle = root / "tools" / "docker" / "images.tar"
    if listing.is_file() and bundle.is_file():
        try:
            references = listing.read_text(encoding="utf-8").split()
        except (OSError, UnicodeError):
            references = []
        for reference in references:
            available.setdefault(_canonical_reference(reference), bundle)
    for path in _image_archive_candidates(root):
        if path == bundle and available:
            continue
        for tag in _repository_tags(path):
            available.setdefault(_canonical_reference(tag), path)
    return available


def _image_archive_candidates(root: Path) -> Iterator[Path]:
    vrnetlab = root / "tools" / "vrnetlab"
    for directory, directories, files in os.walk(root, topdown=True, followlinks=False):
        base = Path(directory)
        if base == vrnetlab:
            directories[:] = []
            continue
        directories[:] = sorted(name for name in directories if name not in _UNSCANNED)
        for name in sorted(files):
            path = base / name
            if path.is_symlink() or not path.is_file():
                continue
            if name.lower().endswith(_IMAGE_ARCHIVE_SUFFIXES):
                yield path


def _repository_tags(path: Path) -> tuple[str, ...]:
    """Return the references a ``docker save`` archive carries, or nothing."""
    try:
        with tarfile.open(path, "r:*") as tar:
            member = tar.getmember("manifest.json")
            handle = tar.extractfile(member)
            if handle is None:
                return ()
            manifest: Any = json.loads(handle.read().decode("utf-8"))
    except (KeyError, OSError, tarfile.TarError, UnicodeError, json.JSONDecodeError):
        return ()
    if not isinstance(manifest, list):
        return ()
    tags: list[str] = []
    for entry in manifest:
        if not isinstance(entry, dict):
            continue
        for tag in entry.get("RepoTags") or ():
            if isinstance(tag, str) and tag.strip():
                tags.append(tag.strip())
    return tuple(tags)


def _canonical_reference(reference: str) -> str:
    value = reference.strip()
    if "@" in value:
        return value
    _, _, tail = value.rpartition("/")
    return value if ":" in tail else f"{value}:latest"


def _load_images(into: Path, selected: Mapping[str, str], notes: list[str]) -> None:
    """Load the selected archives now for references Docker does not already have.

    Only archives a node was actually pointed at are loaded, so an unrelated
    tarball shipped beside the lab never reaches the daemon.
    """
    if not selected:
        return
    if shutil.which("docker") is None:
        notes.append("docker is unavailable; bundled images stay for deploy to load")
        return
    for reference, relative in sorted(selected.items()):
        if _image_present(reference):
            continue
        archive = into / relative
        loaded = subprocess.run(
            ["docker", "image", "load", "--input", str(archive)],
            capture_output=True,
            text=True,
            check=False,
        )
        if loaded.returncode:
            notes.append(f"could not load {relative}; deploy will retry")
        else:
            notes.append(f"loaded {reference} from the bundled {relative}")


def _image_present(reference: str) -> bool:
    result = subprocess.run(
        ["docker", "image", "inspect", reference],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def _resolve_licenses(
    document: dict[str, Any],
    answers: Mapping[str, str],
    notes: list[str],
    *,
    prompt: bool,
    ask: Callable[[str], str | None] | None,
    environment: Mapping[str, str],
) -> None:
    """Replace every frozen license marker with a recipient-owned selection.

    Values are never logged or recorded: only the node name is, exactly as
    engulf-clab-license-pool keeps pool paths out of its own diagnostics.
    """
    assigned = 0
    nodes = _nodes(document)
    for effective in effective_nodes(document):
        name = effective.name
        if effective.data.get("license") != _LICENSE_PROMPT:
            continue
        node = nodes[name]
        if node is None:
            node = nodes[name] = {}
        # Leave a per-node marker even without an answer: license-pool consumes
        # recipient prompts per node, never a shared inherited claim identity.
        node["license"] = _LICENSE_PROMPT
        variable = _node_license_environment(name)
        answer = answers.get(name) or answers.get("*")
        if answer is None:
            answer = environment.get(variable) or environment.get(_LICENSE_ENV)
        if answer is None and prompt:
            answer = (ask or _ask_license)(name)
        if answer is None:
            notes.append(
                f"node {name} keeps its license prompt; deploy asks or reads {variable}"
            )
            continue
        node["license"] = _license_value(name, answer)
        assigned += 1
    if assigned:
        notes.append(
            f"wrote {assigned} license selection(s) into the topology; "
            "do not commit or re-share this lab directory"
        )


def _node_license_environment(node_name: str) -> str:
    """Mirror engulf-clab-license-pool's per-node variable derivation exactly."""
    node = "".join(
        character if character.isalnum() else "_" for character in node_name.upper()
    )
    return f"{_LICENSE_ENV}_{node}"


def _license_value(node_name: str, answer: str) -> str:
    value = answer.strip()
    if not value:
        raise DefrostError(f"node {node_name} license answer is empty")
    if value.startswith("$"):
        return value
    path = Path(value).expanduser()
    if not path.exists():
        raise DefrostError(f"node {node_name} license path does not exist")
    return str(path.resolve())


def _ask_license(node_name: str) -> str | None:
    """Ask an interactive recipient for one node's license file, pool, or variable."""
    if not sys.stdin.isatty():
        return None
    while True:
        try:
            answer = input(
                f"License for node {node_name} "
                "(file, pool directory, $VARIABLE, or empty to skip): "
            )
        except EOFError:
            return None
        value = answer.strip()
        if not value:
            return None
        if value.startswith("$") or Path(value).expanduser().exists():
            return value
        print(
            "That path does not exist. Enter an existing path, a $VARIABLE, or nothing."
        )


def _report_vrnetlab_inputs(
    topology_path: Path,
    document: dict[str, Any],
    notes: list[str],
    *,
    environment: Mapping[str, str],
) -> None:
    """Name the entitled vendor VM inputs an offline archive left to the recipient."""
    try:
        requests = build_requests_from_topology(topology_path, document, environment)
    except Exception as error:  # noqa: BLE001 - unresolved recipient-owned inputs are expected.
        notes.append(f"could not resolve vrnetlab image inputs: {error}")
        return
    for request in requests:
        source = request.source
        if source is None or not source.is_file():
            notes.append(
                f"node {request.node_name} needs an entitled vrnetlab image input before deploy"
            )


def _write_record(
    path: Path,
    archive: Path,
    topology: Path,
    metadata: Mapping[str, Any],
    notes: list[str],
) -> None:
    """Keep the removed freeze provenance beside the lab instead of inside it."""
    record = {
        "version": _RECORD_VERSION,
        "archive": archive.name,
        "topology": topology.as_posix(),
        "freeze": dict(metadata),
        "notes": list(notes),
    }
    path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _publish(root: Path, into: Path, work: Path, *, replacing: bool) -> None:
    """Rename the finished lab into place, restoring a replaced directory on failure.

    Only a destination the caller validated is moved aside. A directory that
    appeared since then fails the rename instead of being replaced unchecked.
    """
    previous = work / "previous"
    replaced = replacing and into.is_dir()
    if replaced:
        into.rename(previous)
    try:
        root.rename(into)
    except OSError:
        if replaced:
            previous.rename(into)
        raise
    if replaced:
        shutil.rmtree(previous, ignore_errors=True)


def _log(logger: PluginLogger | None, message: str) -> None:
    if logger is None:
        print(f"defrost: {message}", file=sys.stderr)
    else:
        logger.info("%s", message)


def lease(arguments: list[str], cwd: Path) -> str:
    """Return the destination lease name without argparse side effects.

    The plugin needs this before the command parses its own arguments, so it
    scans for the destination the same way the parser resolves it and falls back
    to the invocation directory that holds the default destination.
    """
    values = {"--into", "--license"}
    archive: str | None = None
    into: str | None = None
    pending: str | None = None
    for argument in arguments:
        if pending is not None:
            if pending == "--into":
                into = argument
            pending = None
            continue
        if argument in values:
            pending = argument
        elif argument.startswith("--into="):
            into = argument.removeprefix("--into=")
        elif not argument.startswith("-") and archive is None:
            archive = argument
    try:
        if into:
            return f"eclab-defrost:{_resolve(cwd, into)}"
        if archive:
            return f"eclab-defrost:{destination(Path(archive), None, cwd)}"
    except (OSError, ValueError):
        pass
    return f"eclab-defrost:{cwd}"
