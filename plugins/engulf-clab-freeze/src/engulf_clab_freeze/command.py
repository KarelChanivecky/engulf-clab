"""Implementation of the ``eclab freeze`` control command."""

from __future__ import annotations

import argparse
import base64
import fnmatch
import hashlib
import importlib.metadata
import importlib.resources
import json
import os
import re
import shlex
import shutil
import string
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import yaml  # type: ignore[import-untyped]
from engulf_api import PluginLogger, StateStore
from engulf_clab_freeze_api import (
    FreezeContext,
    discover_contributors,
    runtime_provider,
)
from engulf_clab_freeze_api import FreezeError as ContributorError
from engulf_clab_lab_parser import (
    effective_nodes,
    parse_topology_yaml,
    topology_declarations,
)
from engulf_clab_lab_parser.environment import env_file_for_topology
from engulf_clab_lab_parser.session import (
    WRITER_TEMP_PREFIX,
    TopologyError,
    load_topology,
    topology_path_from_args,
)
from engulf_clab_schema_api import RuntimeRequirement

from .host_requirements import write_host_requirements
from .images import freeze_images
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
        ".eclab-freeze.env",
        ".eclab-runtime",
        "__pycache__",
        "build",
        "dist",
        "initialize-env.sh",
    }
)
_LICENSE_SUFFIXES = (".lic", ".license", ".licence")
# A lab's `<name>.env` holds owner-private values the topology expands from.
# A freeze archive is made to be handed to someone else, so these never travel
# with it -- the recipient supplies their own.
_PRIVATE_SUFFIXES = (".env",)
_FREEZE_KEY = "x-engulf-clab-freeze"
_FREEZE_RECORD_NAME = "freeze.json"
_ENV_INITIALIZER = "initialize-env.sh"
_DEFROST_RUNTIME_ENV = "ECLAB_FREEZE_RUNTIME"


class FreezeError(ContributorError):
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
    requirements: tuple[RuntimeRequirement, ...] = (),
) -> int:
    """Run the optional freeze command with an injected workspace state."""
    parser = argparse.ArgumentParser(prog=program)
    parser.add_argument(
        "lab_dir",
        nargs="?",
        metavar="LAB_DIR",
        help="lab directory containing one source topology (default: current directory)",
    )
    parser.add_argument(
        "-t",
        "--eclab-topology",
        dest="topology",
        metavar="TOPOLOGY",
        help="select a topology file instead of discovering one in LAB_DIR",
    )
    parser.add_argument(
        "--eclab-output",
        dest="output",
        metavar="PACKAGE",
        help="destination package (.tar.gz/.tgz for lean; .run for runtime or offline)",
    )
    parser.add_argument(
        "--eclab-offline",
        dest="offline",
        action="store_true",
        help="write a self-extracting .run package with the runtime, tools, and lab images for offline use",
    )
    parser.add_argument(
        "--eclab-with-runtime",
        action="store_true",
        help="write a self-extracting .run package with runtime/, lab.tgz, and a defrost.sh that builds the venv before defrosting",
    )
    parser.add_argument(
        "--eclab-external-image",
        dest="external_image",
        action="append",
        default=[],
        metavar="IMAGE",
        help="declare that the recipient supplies this image (repeatable)",
    )
    parser.add_argument(
        "--eclab-bundle-image",
        dest="bundle_image",
        action="append",
        default=[],
        metavar="IMAGE",
        help="capture this image in an offline archive (repeatable; requires --eclab-offline)",
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
        if arguments.topology and arguments.lab_dir is not None:
            parser.error("LAB_DIR and -t/--eclab-topology cannot be used together")
    except SystemExit as error:
        return int(error.code or 0)
    try:
        topology_args = ("-t", arguments.topology) if arguments.topology else ()
        lab_dir = (
            Path(arguments.lab_dir).expanduser().resolve()
            if arguments.lab_dir
            else None
        )
        if lab_dir is not None and not lab_dir.is_dir():
            raise FreezeError(f"lab directory does not exist: {lab_dir}")
        topology = topology_path_from_args(topology_args, cwd=lab_dir)
        runtime_package = arguments.offline or arguments.eclab_with_runtime
        archive = (
            Path(arguments.output).expanduser().resolve()
            if arguments.output
            else _default_archive(topology, self_extracting=runtime_package)
        )
        freeze(
            topology,
            archive,
            workspace=workspace,
            confirm_overwrite=_confirm_overwrite,
            offline=arguments.offline,
            with_runtime=arguments.eclab_with_runtime,
            external_images=tuple(arguments.external_image),
            bundle_images=tuple(arguments.bundle_image),
            user_state=user_state,
            application_name=application_name,
            environment=environment,
            contributors=contributors,
            contributor_arguments=arguments,
            requirements=requirements,
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
    with_runtime: bool = False,
    external_images: tuple[str, ...] = (),
    bundle_images: tuple[str, ...] = (),
    user_state: StateStore | None = None,
    application_name: str = "eclab",
    environment: Mapping[str, str] | None = None,
    contributors: tuple[Any, ...] = (),
    contributor_arguments: argparse.Namespace | None = None,
    requirements: tuple[RuntimeRequirement, ...] = (),
) -> bool:
    """Create a lean/offline lab archive or a runtime bundle containing one."""
    topology_path = topology_path.expanduser().resolve()
    archive = archive.expanduser().resolve()
    source_root = topology_path.parent.resolve()
    current_environment = os.environ if environment is None else environment
    if offline and with_runtime:
        raise FreezeError(
            "--eclab-offline cannot be combined with --eclab-with-runtime"
        )
    mode = "offline" if offline else "runtime" if with_runtime else "lean"
    if bundle_images and not offline:
        raise FreezeError("--eclab-bundle-image requires --eclab-offline")
    provider = runtime_provider(application_name)
    ignored_archives = tracked_archives(workspace, source_root)
    if mode == "lean" and not archive.name.endswith((".tar.gz", ".tgz")):
        raise FreezeError("lean --eclab-output must end in .tar.gz or .tgz")
    if mode != "lean" and not archive.name.endswith(".run"):
        raise FreezeError("runtime and offline --eclab-output paths must end in .run")
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
        packages = _installed_packages()
        user_directory = getattr(user_state, "directory", None)
        tools = dict(provider.capture(current_environment, user_directory))
        frozen = _freeze_topology(
            copied_topology,
            source_root,
            staging,
            packages,
            warnings,
            offline=offline,
            environment=current_environment,
        )
        frozen.update(
            format=3,
            mode=mode,
            producer_edition=application_name,
            tools=tools,
            runtime_packages=[name for name, _ in _locked_packages(application_name)],
        )
        contribution_metadata: dict[str, Any] = {}
        for contributor in contributors:
            contributed = contributor.freeze(
                FreezeContext(
                    source_topology=topology_path,
                    staged_topology=copied_topology,
                    source_root=source_root,
                    staging_root=staging,
                    workspace_state=_contributor_state(
                        workspace.directory if workspace is not None else None,
                        contributor.contributor_id,
                    ),
                    user_state=_contributor_state(
                        user_directory, contributor.contributor_id
                    ),
                    arguments=contributor_arguments or argparse.Namespace(),
                    environment=current_environment,
                )
            )
            if contributed is not None:
                contribution_metadata[contributor.contributor_id] = dict(contributed)
        if contribution_metadata:
            frozen["contributors"] = contribution_metadata
        image_topology = yaml.safe_load(copied_topology.read_text(encoding="utf-8"))
        try:
            image_plan = freeze_images(
                topology_path,
                image_topology,
                staging,
                current_environment,
                offline=offline,
                lean=not offline,
                external_images=external_images,
                bundle_images=bundle_images,
            )
        except ContributorError as error:
            raise FreezeError(str(error)) from error
        frozen["image_plan"] = image_plan
        copied_topology.write_text(
            yaml.safe_dump(image_topology, sort_keys=False), encoding="utf-8"
        )
        _write_freeze_record(staging, topology_path.name, frozen)
        (staging / "packages.freeze.txt").write_text(
            "\n".join(f"{name}=={version}" for name, version in packages) + "\n",
            encoding="utf-8",
        )
        runtime_root: Path | None = None
        if mode == "runtime":
            runtime_root = Path(work) / "runtime"
            runtime_root.mkdir()
            shutil.copy2(
                staging / _FREEZE_RECORD_NAME,
                runtime_root / _FREEZE_RECORD_NAME,
            )
            shutil.copy2(
                staging / "packages.freeze.txt",
                runtime_root / "packages.freeze.txt",
            )
            provider.prepare_archive(
                runtime_root,
                mode,
                tools,
                current_environment,
                user_directory,
                warnings,
            )
            runtime_launcher = provider.launcher(topology_path.name, mode, tools)
            (runtime_root / _launcher_name(application_name)).write_text(
                runtime_launcher, encoding="utf-8"
            )
            os.chmod(runtime_root / _launcher_name(application_name), 0o755)
        else:
            provider.prepare_archive(
                staging, mode, tools, current_environment, user_directory, warnings
            )
        write_host_requirements(
            staging,
            requirements,
            frozen,
            source,
            artifact_root=runtime_root,
        )
        _write_environment_initializer(copied_topology, staging)
        _prune_empty_directories(staging)
        (staging / "FREEZE-WARNINGS.txt").write_text(
            "\n".join(f"- {warning}" for warning in warnings)
            + ("\n" if warnings else ""),
            encoding="utf-8",
        )
        launcher_name = _launcher_name(application_name)
        launcher_text = provider.launcher(topology_path.name, mode, tools)
        (staging / launcher_name).write_text(launcher_text, encoding="utf-8")
        os.chmod(staging / launcher_name, 0o755)
        substitutions = {
            "topology": topology_path.name,
            "edition": application_name,
            "launcher": launcher_name,
        }
        readme = _freeze_readme(
            mode,
            topology_name=topology_path.name,
            edition=application_name,
            launcher_name=launcher_name,
            licensed_nodes=_licensed_nodes(image_topology),
        )
        supplement = string.Template(provider.readme_supplement(mode)).substitute(
            **substitutions
        )
        if supplement:
            readme = readme.rstrip("\n") + "\n\n" + supplement.rstrip("\n") + "\n"
        (staging / FREEZE_README_NAME).write_text(readme, encoding="utf-8")
        temporary_archive = Path(work) / archive.name
        if mode in {"runtime", "offline"}:
            bundle_root = Path(work) / f"{root_name}-bundle"
            bundle_root.mkdir()
            if mode == "runtime":
                assert runtime_root is not None
                shutil.copytree(runtime_root, bundle_root / "runtime")
                defroster = _runtime_bundle_defroster(_launcher_name(application_name))
                bundle_readme = _runtime_bundle_readme(
                    application_name,
                    topology_path.name,
                    _launcher_name(application_name),
                )
            else:
                offline_runtime = bundle_root / "runtime"
                offline_runtime.mkdir()
                shutil.copytree(
                    staging / ".eclab-venv", offline_runtime / ".eclab-venv"
                )
                shutil.rmtree(staging / ".eclab-venv")
                defroster = _offline_bundle_defroster(application_name)
                bundle_readme = _offline_bundle_readme(
                    application_name,
                    topology_path.name,
                    _launcher_name(application_name),
                )
            nested_lab = bundle_root / "lab.tgz"
            with tarfile.open(nested_lab, "w:gz") as tar:
                tar.add(staging, arcname=root_name, recursive=True)
            (bundle_root / "defrost.sh").write_text(
                defroster,
                encoding="utf-8",
            )
            (bundle_root / "defrost.sh").chmod(0o755)
            (bundle_root / "README.md").write_text(
                bundle_readme,
                encoding="utf-8",
            )
            payload_archive = Path(work) / f"{root_name}.payload.tar.gz"
            with tarfile.open(payload_archive, "w:gz") as tar:
                _add_directory_contents(tar, bundle_root)
            _write_self_extracting_archive(
                temporary_archive, payload_archive, archive.name
            )
        else:
            with tarfile.open(temporary_archive, "w:gz") as tar:
                tar.add(staging, arcname=root_name, recursive=True)
        if mode != "lean":
            temporary_archive.chmod(0o755)
        track_archive(workspace, source_root, archive)
        temporary_archive.replace(archive)
    return True


FREEZE_README_NAME = "FREEZE-README.md"


def _write_freeze_record(
    staging: Path, topology_name: str, metadata: Mapping[str, Any]
) -> None:
    """Store provenance beside the lab without extending Containerlab YAML."""
    record = {
        "version": 1,
        "topology": topology_name,
        "freeze": dict(metadata),
    }
    try:
        content = json.dumps(record, indent=2, sort_keys=True) + "\n"
    except (TypeError, ValueError) as error:
        raise FreezeError(
            f"freeze metadata is not JSON serializable: {error}"
        ) from error
    (staging / _FREEZE_RECORD_NAME).write_text(content, encoding="utf-8")


def _freeze_readme(
    mode: str,
    *,
    topology_name: str,
    edition: str,
    launcher_name: str,
    licensed_nodes: Iterable[tuple[str, str | None]] = (),
) -> str:
    """Render the recipient guide this plugin packages for one freeze mode.

    The guide replaces any same-named file from the source lab, so a lab that
    is frozen again always carries the guide for its new mode.
    """
    template = (
        importlib.resources.files(__package__)
        .joinpath("readmes", f"{mode}.md")
        .read_text(encoding="utf-8")
    )
    rendered = string.Template(template).substitute(
        topology=topology_name,
        edition=edition,
        launcher=launcher_name,
        licenses=_license_section(
            mode, tuple(licensed_nodes), edition=edition, launcher_name=launcher_name
        ),
    )
    # An omitted section leaves its surrounding blank lines behind.
    return re.sub(r"\n{3,}", "\n\n", rendered)


def _licensed_nodes(document: Mapping[str, Any]) -> tuple[tuple[str, str | None], ...]:
    """Name each node whose effective license is a recipient prompt, with its kind.

    Only node names and kinds reach the guide; license values were already
    redacted and pool paths are never known to the archive.
    """
    marker = f"__{_LABEL_PREFIX}_LICENSE_PROMPT__"
    licensed: list[tuple[str, str | None]] = []
    for effective in effective_nodes(document):
        if effective.data.get("license") != marker:
            continue
        kind = effective.data.get("kind")
        licensed.append(
            (effective.name, kind if isinstance(kind, str) and kind else None)
        )
    return tuple(licensed)


def _license_section(
    mode: str,
    licensed_nodes: tuple[tuple[str, str | None], ...],
    *,
    edition: str,
    launcher_name: str,
) -> str:
    if not licensed_nodes:
        return ""
    nodes = "\n".join(
        f"- `{name}` (kind `{kind}`)"
        if kind
        else f"- `{name}` (kind not set; check the topology)"
        for name, kind in licensed_nodes
    )
    kinds = sorted({kind for _, kind in licensed_nodes if kind}) or ["KIND"]

    def register(command: str) -> str:
        return "\n".join(
            f"{command} init-license-pool /path/to/{kind}-licenses --kind {kind}"
            for kind in kinds
        )

    lines = [
        "## Licenses",
        "",
        "Freeze removed the producer's licenses. These nodes need one from you:",
        "",
        nodes,
        "",
        "The simplest answer is a license pool: a directory holding license files",
        "directly at its top level. Register one per node kind once; pools belong",
        "to your user account and are shared by every lab you run:",
        "",
        "```bash",
        register(edition),
        f"{edition} defrost ARCHIVE.tar.gz --{_LABEL_PREFIX.lower()}-auto-license",
        "```",
        "",
        "Each deploy then claims a free file for every node, and `destroy` releases",
        "it. `--kind` must match the node's kind exactly.",
    ]
    if mode != "lean":
        lines += [
            "",
            f"Without {edition} installed, register through the launcher and answer",
            "`auto` when deploy asks:",
            "",
            "```bash",
            register(f"./{launcher_name}"),
            f"{_LABEL_PREFIX}_LICENSE=auto ./{launcher_name}",
            "```",
        ]
    lines += [
        "",
        "Instead of `auto` you may answer with a license file, a pool directory, or a",
        f"`$VARIABLE`, through `--{_LABEL_PREFIX.lower()}-license NODE=VALUE` at defrost,",
        f"`{_LABEL_PREFIX}_LICENSE_<NODE>` or `{_LABEL_PREFIX}_LICENSE`, or the",
        "interactive prompt. Node names are uppercased with other characters replaced",
        "by `_` in the variable name.",
    ]
    return "\n".join(lines)


def _default_archive(topology_path: Path, *, self_extracting: bool = False) -> Path:
    root = topology_path.parent.resolve()
    name = root.name or "frozen-lab"
    suffix = ".run" if self_extracting else ".tar.gz"
    return Path.cwd().resolve() / f"{name}{suffix}"


def _archive_root_name(archive: Path) -> str:
    name = (
        archive.name.removesuffix(".tar.gz").removesuffix(".tgz").removesuffix(".run")
    )
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-") or "frozen-lab"


def _write_self_extracting_archive(
    destination: Path, payload: Path, package_name: str
) -> None:
    """Write an executable shell extractor followed by a gzip tar payload."""
    default_output = package_name.removesuffix(".run")
    prefix = f"""#!/bin/sh
set -eu
usage() {{
    echo "Usage: $0 [--eclab-output DIRECTORY] [DEFROST_OPTIONS...]" >&2
}}
output=
while [ "$#" -gt 0 ]; do
    case "$1" in
        --eclab-output)
            [ "$#" -ge 2 ] || {{ usage; exit 2; }}
            [ -n "$2" ] || {{ usage; exit 2; }}
            output=$2
            shift 2
            ;;
        --eclab-output=*)
            output=${{1#*=}}
            [ -n "$output" ] || {{ usage; exit 2; }}
            shift
            ;;
        --)
            shift
            break
            ;;
        *)
            break
            ;;
    esac
done
if [ -z "$output" ]; then
    output=./{shlex.quote(default_output)}
fi
case "$output" in
    /) echo "output must not be the filesystem root" >&2; exit 2 ;;
    */) output=${{output%/}} ;;
esac
if [ -z "$output" ]; then
    usage
    exit 2
fi
if [ -e "$output" ] || [ -L "$output" ]; then
    echo "lab output already exists: $output" >&2
    exit 1
fi
case "$output" in
    /*) ;;
    *) output="$PWD/${{output#./}}" ;;
esac
parent=$(dirname -- "$output")
name=$(basename -- "$output")
mkdir -p -- "$parent"
stage=$(mktemp -d -- "$parent/.${{name}}.extract.XXXXXX")
cleanup() {{ rm -rf -- "$stage"; }}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
tail -n +__PAYLOAD_LINE__ "$0" | tar -xz -C "$stage"
"$stage/defrost.sh" --eclab-output "$output" "$@"
echo "Defrosted lab to $output"
exit 0
__ECLAB_ARCHIVE_BELOW__
"""
    payload_line = prefix.count("\n") + 1
    prefix = prefix.replace("__PAYLOAD_LINE__", str(payload_line))
    with destination.open("wb") as output:
        output.write(prefix.encode("utf-8"))
        with payload.open("rb") as source:
            shutil.copyfileobj(source, output)
    destination.chmod(0o755)


def _add_directory_contents(tar: tarfile.TarFile, directory: Path) -> None:
    """Add a directory's children at the archive root in stable order."""
    for path in sorted(directory.iterdir(), key=lambda entry: entry.name):
        tar.add(path, arcname=path.name, recursive=True)


def _runtime_bundle_defroster(launcher_name: str) -> str:
    """Build the bundled runtime and use it for the normal defrost workflow."""
    edition = launcher_name.removeprefix("run-").removesuffix(".sh")
    return f"""#!/bin/sh
set -eu
caller_cwd=$PWD
case "$0" in */*) root=${{0%/*}}; [ -n "$root" ] || root=/ ;; *) root=. ;; esac
root=$(CDPATH= cd -- "$root" && pwd)
cd -- "$root"
runtime="$root/runtime"
if [ ! -f "$root/lab.tgz" ] || [ ! -x "$runtime/{launcher_name}" ]; then
    echo "runtime bundle is incomplete; expected lab.tgz and runtime/{launcher_name}" >&2
    exit 1
fi
if [ ! -x "$runtime/.eclab-venv/bin/{edition}" ] || [ ! -x "$runtime/.eclab-venv/bin/python" ]; then
    "$runtime/{launcher_name}" --eclab-build-venv
fi
if [ ! -x "$runtime/.eclab-venv/bin/{edition}" ] || [ ! -x "$runtime/.eclab-venv/bin/python" ]; then
    echo "runtime bundle did not create a complete Python environment" >&2
    exit 1
fi
{_DEFROST_RUNTIME_ENV}="$runtime"
ECLAB_FREEZE_CALLER_CWD="$caller_cwd"
export {_DEFROST_RUNTIME_ENV}
export ECLAB_FREEZE_CALLER_CWD
exec "$runtime/.eclab-venv/bin/{edition}" defrost "$root/lab.tgz" "$@"
"""


def _offline_bundle_defroster(edition: str) -> str:
    """Use the copied offline venv to run normal defrost on lab.tgz."""
    return f"""#!/bin/sh
set -eu
caller_cwd=$PWD
case "$0" in */*) root=${{0%/*}}; [ -n "$root" ] || root=/ ;; *) root=. ;; esac
root=$(CDPATH= cd -- "$root" && pwd)
runtime="$root/runtime/.eclab-venv"
if [ ! -f "$root/lab.tgz" ] || [ ! -x "$runtime/bin/{edition}" ]; then
    echo "offline bundle is incomplete; expected lab.tgz and runtime/.eclab-venv/bin/{edition}" >&2
    exit 1
fi
{_DEFROST_RUNTIME_ENV}="$root/runtime"
ECLAB_FREEZE_CALLER_CWD="$caller_cwd"
export {_DEFROST_RUNTIME_ENV}
export ECLAB_FREEZE_CALLER_CWD
exec "$runtime/bin/{edition}" defrost "$root/lab.tgz" "$@"
"""


def _runtime_bundle_readme(edition: str, topology: str, launcher_name: str) -> str:
    return f"""# Runtime bundle for {edition}

This package contains `runtime/` and the frozen lab archive `lab.tgz`.

Running this `.run` package automatically builds the bundled Python environment
if needed and uses it to defrost the lab into `./<package-name>`. Defrost runs the lab's
`initialize-env.sh`, prompts for recipient license values, and prepares the
runtime in the resulting lab directory. When no license pool is registered,
defrost offers to create a license-pool directory and initialize it with the
edition's `init-license-pool` command. The new pool starts empty; add entitled
license files afterward. It reports missing host dependencies
after defrost without blocking it; rerun the report from the restored lab with
`./check-dependencies.sh`. Pass normal defrost options to the `.run` command
when needed, for example `./demo-runtime.run --eclab-license router=/pool`.
Use `--eclab-output DIRECTORY` immediately after the package name to choose a
different lab output directory, before any other defrost options.

The selected topology is `{topology}`. The restored lab's launcher is
`{launcher_name}`.
"""


def _offline_bundle_readme(edition: str, topology: str, launcher_name: str) -> str:
    return f"""# Offline bundle for {edition}

This self-extracting package contains the defrost venv under `runtime/` and the
offline lab archive under `lab.tgz`. Defrost attaches that venv and publishes
the lab with its bundled tools and image archives.

Running the `.run` package invokes `defrost.sh` to expand the lab and resolve
its environment and license values. Defrost publishes the restored lab with
the bundled eclab environment, Containerlab, vrnetlab checkout, and image
archives. The selected topology is
`{topology}`; the restored launcher is `{launcher_name}`.

Deploy still requires host Docker and the kernel, device, or networking
facilities required by Containerlab.
"""


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


def _contributor_state(directory: Path | None, contributor_id: str) -> Path | None:
    """Select a contributor's sibling namespace in the Engulf state catalog.

    Callback-bound stores belong to freeze. Contributors need their own state
    (for example PKI's global catalog and issued identities). Do not create or
    mutate another plugin's directory while discovering its existing material.
    """
    if re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+", contributor_id) is None:
        raise FreezeError("invalid freeze contributor state namespace")
    if directory is None:
        return None
    selected = directory.parent / contributor_id
    if selected.is_symlink():
        raise FreezeError("freeze contributor state directory must not be a symlink")
    return selected


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
        or relative == Path(_FREEZE_RECORD_NAME)
        or relative.name in _BUILTIN_IGNORES
        or (
            relative.parent == Path(".")
            and re.fullmatch(r"\.[a-z0-9_]+-defrost\.json", relative.name) is not None
        )
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


def _write_environment_initializer(copied_topology: Path, staging_root: Path) -> None:
    """Add the recipient-side helper for the topology's private env file."""
    document = parse_topology_yaml(copied_topology.read_text(encoding="utf-8"))
    references: set[str] = set()
    if isinstance(document, dict):
        document = dict(document)
        document.pop(_FREEZE_KEY, None)
    _collect_environment_references(document, references)
    env_name = env_file_for_topology(copied_topology).name
    script = staging_root / _ENV_INITIALIZER
    script.write_text(
        _environment_initializer_script(env_name, sorted(references)),
        encoding="utf-8",
    )
    os.chmod(script, 0o755)


def _collect_environment_references(value: object, references: set[str]) -> None:
    if isinstance(value, str):
        references.update(_environment_references(value))
    elif isinstance(value, Mapping):
        for key, item in value.items():
            _collect_environment_references(key, references)
            _collect_environment_references(item, references)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _collect_environment_references(item, references)


def _environment_references(value: str) -> set[str]:
    """Find the variable names accepted by the lab parser's expansion syntax."""
    references: set[str] = set()
    index = 0
    while index < len(value):
        if value[index] != "$":
            index += 1
            continue
        if index + 1 >= len(value) or value[index + 1] == "$":
            index += 2
            continue
        following = value[index + 1]
        if following == "{":
            start = index + 2
            end = start
            while end < len(value) and _environment_character(value[end]):
                end += 1
            name = value[start:end]
            if name and not name[0].isdigit():
                references.add(name)
            # Continue one character later so nested defaults such as
            # ${IMAGE:-$DEFAULT_IMAGE} are also offered to the recipient.
            index += 2
            continue
        if not _environment_character(following) or following.isdigit():
            index += 1
            continue
        end = index + 2
        while end < len(value) and _environment_character(value[end]):
            end += 1
        references.add(value[index + 1 : end])
        index = end
    return references


def _environment_character(value: str) -> bool:
    return value == "_" or value.isalnum()


def _environment_initializer_script(env_name: str, references: list[str]) -> str:
    quoted_env_name = shlex.quote(env_name)
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "umask 077",
        'root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"',
        f'env_file="$root"/{quoted_env_name}',
        "",
        'if [[ -L "$env_file" || ( -e "$env_file" && ! -f "$env_file" ) ]]; then',
        "    printf 'refusing to write a non-regular env file: %s\\n' \"$env_file\" >&2",
        "    exit 1",
        "fi",
        "",
        'tmp=""',
        "cleanup() {",
        '    [[ -z "$tmp" ]] || rm -f -- "$tmp"',
        "}",
        "trap cleanup EXIT",
        "changed=0",
        "printed_help=0",
    ]
    if not references:
        lines.extend(
            [
                "exit 0",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "append_value() {",
                '    local name="$1" value="$2" escaped',
                '    if [[ -z "$tmp" ]]; then',
                '        tmp="$(mktemp "$env_file.tmp.XXXXXX")"',
                '        if [[ -f "$env_file" ]]; then cat "$env_file" > "$tmp"; fi',
                '        chmod 600 "$tmp"',
                "    fi",
                '    escaped="$(printf \'%s\' "$value" | sed \'s/\\\\/\\\\\\\\/g; s/"/\\\\"/g\')"',
                '    printf \'%s="%s"\\n\' "$name" "$escaped" >> "$tmp"',
                "    changed=1",
                "}",
                "",
            ]
        )
        for name in references:
            lines.extend(
                [
                    f"if [[ -v {name} ]]; then",
                    f'    value="${{{name}}}"',
                    "else",
                    '    if [[ "$printed_help" -eq 0 ]]; then',
                    "        printf '\\nThis lab needs recipient-specific environment values.\\n'",
                    "        printf 'The restored lab includes FREEZE-README.md with setup and run instructions.\\n\\n'",
                    "        printed_help=1",
                    "    fi",
                    f"    printf 'Value for {name} (leave empty to set it later): '",
                    "    IFS= read -r value || value=",
                    "fi",
                    'if [[ -z "$value" ]]; then',
                    f"    printf 'Left {name} unset.\\n'",
                    "else",
                    f'    append_value {name} "$value"',
                    "fi",
                    "",
                ]
            )
        lines.extend(
            [
                'if [[ "$changed" -eq 1 ]]; then',
                '    mv -f -- "$tmp" "$env_file"',
                '    tmp=""',
                '    chmod 600 "$env_file"',
                "    printf 'wrote recipient values to %s\\n' \"$env_file\"",
                "else",
                "    printf 'No environment values were added. You can run initialize-env.sh later.\\n'",
                "fi",
            ]
        )
    return "\n".join(lines) + "\n"


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
    freeze_metadata: dict[str, Any] = {
        "format": 2,
        "application": "engulf-clab",
        "packages": [{"name": name, "version": version} for name, version in packages],
        "tools": _tool_provenance(current_environment),
        "licenses": "prompt",
        "offline": offline,
        "env_initializer": _ENV_INITIALIZER,
    }
    copied.pop(_FREEZE_KEY, None)
    copied_path.write_text(yaml.safe_dump(copied, sort_keys=False), encoding="utf-8")
    return freeze_metadata


def _bundle_offline_runtime(staging: Path, edition: str) -> None:
    """Copy the active, installed edition virtual environment into the archive."""
    source = Path(sys.prefix).resolve()
    if sys.prefix == sys.base_prefix or not (source / "bin" / edition).is_file():
        raise FreezeError(
            f"--eclab-offline requires freeze to run from a virtual environment containing {edition}"
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
        or not (destination / "bin" / edition).is_file()
    ):
        raise FreezeError(
            f"could not create a complete offline {edition} virtual environment"
        )
    _remove_venv_creation_path(destination)
    _make_console_scripts_portable(destination)


def _remove_venv_creation_path(venv: Path) -> None:
    """Drop the informational command that records where the venv was made."""
    configuration = venv / "pyvenv.cfg"
    try:
        lines = configuration.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return
    portable = [
        line for line in lines if line.partition("=")[0].strip().lower() != "command"
    ]
    configuration.write_text("\n".join(portable) + "\n", encoding="utf-8")


def _make_console_scripts_portable(venv: Path) -> None:
    """Make copied Python entry points use the interpreter beside the archive."""
    binaries = venv / "bin"
    scripts: list[tuple[Path, bytes]] = []
    for entry in sorted(binaries.iterdir()):
        if entry.is_symlink() or not entry.is_file():
            continue
        try:
            content = entry.read_bytes()
        except OSError:
            continue
        body = _console_script_body(content)
        if body is not None:
            scripts.append((entry, body))
    if not scripts:
        return

    sidecars = binaries / ".eclab-frozen-scripts"
    try:
        sidecars.mkdir()
    except FileExistsError as error:
        raise FreezeError(
            "offline runtime already contains the reserved "
            ".eclab-frozen-scripts directory"
        ) from error

    runner = (
        "import os,sys\n"
        "launcher,script,script_dir=sys.argv[1:4]\n"
        "sys.argv[:]=[launcher,*sys.argv[4:]]\n"
        "sys.path[0]=script_dir\n"
        "namespace={'__name__':'__main__','__file__':script}\n"
        "with open(script,'rb') as source:\n"
        "    code=compile(source.read(),script,'exec')\n"
        "exec(code,namespace)\n"
    )
    for entry, body in scripts:
        script_name = hashlib.sha256(entry.name.encode("utf-8")).hexdigest() + ".py"
        script = sidecars / script_name
        script.write_bytes(body)
        script.chmod(0o644)
        wrapper = (
            "#!/bin/sh\n"
            'case "$0" in */*) script_dir=${0%/*} ;; *) script_dir=. ;; esac\n'
            f'exec "$script_dir/python" -c {shlex.quote(runner)} '
            f'"$0" "$script_dir/.eclab-frozen-scripts/{script_name}" '
            '"$script_dir" "$@"\n'
        )
        entry.write_text(wrapper, encoding="utf-8")
        entry.chmod(0o755)


def _console_script_body(content: bytes) -> bytes | None:
    """Return Python launcher code without its source-environment shebang."""
    lines = content.splitlines(keepends=True)
    if len(lines) < 2:
        return None
    first = lines[0].lower()
    if first.startswith(b"#!") and b"python" in first:
        return b"".join(lines[1:])
    # distlib uses this shell trampoline when an interpreter path is too long
    # for the operating system's shebang limit.
    if (
        first.startswith(b"#!/bin/sh")
        and len(lines) >= 4
        and lines[1].lstrip().startswith(b"'''exec' ")
        and b"python" in lines[1].lower()
        and lines[2].strip() == b"' '''"
    ):
        return b"".join(lines[3:])
    return None


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
        "--eclab-offline requires an executable Containerlab in CONTAINERLAB_BIN, "
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
        "--eclab-offline requires a valid VRNETLAB_DIR or managed vrnetlab checkout "
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
    # Git otherwise walks up into the recipient lab's repository and reports
    # its changes as if they belonged to this Git-less frozen tree.
    (destination / ".git").write_text(
        "frozen vrnetlab tree; no Git metadata\n", encoding="ascii"
    )
    if not (destination / "common" / "vrnetlab.py").is_file():
        raise FreezeError("could not create a complete offline vrnetlab checkout")


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


def _launcher_name(application_name: str) -> str:
    """Return the archive launcher filename for the producing edition.

    The launcher is the first thing a recipient runs and names the command it
    executes, so it follows the edition rather than a fixed upstream spelling:
    eclab produces ``run-eclab.sh``, fclab produces ``run-fclab.sh``. Matching
    the console script keeps the filename a trustworthy label, and mirrors how
    the state directory and ignore-file already derive from the same metadata.
    """
    prefix = _state_prefix(application_name).lower()
    return f"run-{prefix}.sh"


def _shell_quote(value: str) -> str:
    return shlex.quote(value)


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


def _locked_packages(edition: str = "eclab") -> list[tuple[str, str]]:
    names = {"engulf-clab", edition}
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


def _installed_packages() -> list[tuple[str, str]]:
    """Record all installed names and versions without direct URL material."""
    return sorted(
        {
            (
                distribution.metadata["Name"].lower().replace("_", "-"),
                distribution.version,
            )
            for distribution in importlib.metadata.distributions()
            if distribution.metadata.get("Name") and distribution.version
        }
    )


# The oldest CPython the Engulf family supports; runtime wheelhouses cover
# every minor from here to the producer's own.
_MINIMUM_PYTHON_MINOR = 12
PYTHON_VERSIONS_NAME = "python-versions.freeze.txt"


def _download_python_wheels(staging: Path, warnings: list[str]) -> list[str]:
    """Extend a complete wheelhouse to every supported recipient Python.

    The recipient installs without a package index, so each CPython minor
    needs its own compiled wheels; pure wheels already serve every minor.
    Only minors whose compiled packages all resolved are recorded, and the
    producer's own minor always is.
    """
    wheelhouse = staging / "wheelhouse"
    compiled = sorted(
        f"{name}=={version}"
        for (name, version), tags in _wheel_tags(wheelhouse).items()
        if not any(platform == "any" for _python, _abi, platform in tags)
    )
    current = sys.version_info[1]
    supported = []
    for minor in range(min(_MINIMUM_PYTHON_MINOR, current), current + 1):
        version = f"3.{minor}"
        if minor != current and compiled:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "download",
                    "--only-binary=:all:",
                    "--no-deps",
                    "--python-version",
                    version,
                    "--dest",
                    str(wheelhouse),
                    *compiled,
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            if result.returncode:
                warnings.append(
                    f"recipients cannot use Python {version}: its wheels are unavailable"
                )
                continue
        supported.append(version)
    (staging / PYTHON_VERSIONS_NAME).write_text(
        "".join(f"{version}\n" for version in supported), encoding="ascii"
    )
    return supported


def _download_wheels(
    staging: Path, packages: list[tuple[str, str]], warnings: list[str]
) -> bool:
    """Collect the producer's installed packages, then download only the rest.

    Installed artifacts are authoritative: an index copy of the same version
    may differ or not exist at all, so pip is asked only for packages the
    producer could not supply itself.
    """
    wheelhouse = staging / "wheelhouse"
    wheelhouse.mkdir()
    _seed_installed_wheels(packages, wheelhouse, warnings)
    present = _wheel_tags(wheelhouse)
    missing = [
        (name, version)
        for name, version in packages
        if (_normalized_name(name), version) not in present
    ]
    returncode = 0
    if missing:
        (staging / "requirements.missing.txt").write_text(
            "".join(f"{name}=={version}\n" for name, version in missing),
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "download",
                "--only-binary=:all:",
                "--no-deps",
                "--dest",
                str(wheelhouse),
                "-r",
                str(staging / "requirements.missing.txt"),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        (staging / "requirements.missing.txt").unlink()
        returncode = result.returncode
    if returncode:
        warnings.append(
            "could not obtain a complete wheelhouse; launcher will fall back to its package index"
        )
    if not any(wheelhouse.iterdir()):
        wheelhouse.rmdir()
    return returncode == 0 and wheelhouse.is_dir()


def _normalized_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _wheel_tags(wheelhouse: Path) -> dict[tuple[str, str], list[tuple[str, str, str]]]:
    """Index wheel files by normalized project name and version."""
    tags: dict[tuple[str, str], list[tuple[str, str, str]]] = {}
    for path in wheelhouse.glob("*.whl"):
        parts = path.name[: -len(".whl")].split("-")
        if len(parts) < 5:
            continue
        key = (_normalized_name(parts[0]), parts[1])
        tags.setdefault(key, []).append((parts[-3], parts[-2], parts[-1]))
    return tags


def _seed_installed_wheels(
    packages: Iterable[tuple[str, str]], wheelhouse: Path, warnings: list[str]
) -> None:
    """Capture every installed package as the producer actually has it.

    A recorded local wheel is copied, an editable project is built from its
    live source, and any other pure-Python installation is repacked from its
    installed files. Only compiled packages from an index are left for pip.
    """
    for name, _version in packages:
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            continue
        source = _installed_wheel_path(distribution)
        if source is not None:
            try:
                shutil.copy2(source, wheelhouse / source.name)
            except OSError as error:
                warnings.append(f"could not copy installed wheel for {name}: {error}")
            continue
        directory = _installed_source_directory(distribution)
        if directory is not None:
            _build_source_wheel(name, directory, wheelhouse, warnings)
            continue
        try:
            _repack_installed_wheel(distribution, wheelhouse)
        except OSError as error:
            warnings.append(f"could not repack installed {name}: {error}")


def _installed_source_directory(
    distribution: importlib.metadata.Distribution,
) -> Path | None:
    """Return the live project behind an editable install."""
    record = _direct_url(distribution)
    dir_info = record.get("dir_info") if record else None
    if record is None or not isinstance(dir_info, dict) or not dir_info.get("editable"):
        return None
    parsed = urlsplit(record["url"])
    if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
        return None
    directory = Path(unquote(parsed.path))
    return directory if (directory / "pyproject.toml").is_file() else None


def _direct_url(distribution: importlib.metadata.Distribution) -> dict[str, Any] | None:
    try:
        content = distribution.read_text("direct_url.json")
        record: object = json.loads(content) if content is not None else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(record, dict) or not isinstance(record.get("url"), str):
        return None
    return record


def _build_source_wheel(
    name: str, directory: Path, wheelhouse: Path, warnings: list[str]
) -> None:
    """Freeze an editable project as its current source, not an index copy."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--wheel-dir",
            str(wheelhouse),
            str(directory),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        warnings.append(f"could not build a wheel for {name} from its installed source")


_REGENERATED_METADATA = {"RECORD", "INSTALLER", "REQUESTED", "direct_url.json"}
# Fixed so repacking the same installation produces the same archive bytes.
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _repack_installed_wheel(
    distribution: importlib.metadata.Distribution, wheelhouse: Path
) -> bool:
    """Rebuild a pure-Python wheel from the files pip installed.

    Console scripts outside site-packages are regenerated from entry points
    at install time; any other file outside site-packages means the wheel
    cannot be reconstructed, so the package is left for the index.
    """
    wheel = distribution.read_text("WHEEL") or ""
    tags = [
        line.split(":", 1)[1].strip()
        for line in wheel.splitlines()
        if line.startswith("Tag:")
    ]
    if (
        "Root-Is-Purelib: true" not in wheel
        or not tags
        or any(not tag.endswith("-none-any") for tag in tags)
    ):
        return False
    files = distribution.files
    if not files:
        return False
    scripts = {
        point.name
        for point in distribution.entry_points
        if point.group in {"console_scripts", "gui_scripts"}
    }
    base = Path(str(distribution.locate_file("")))
    entries: list[str] = []
    dist_info: str | None = None
    for entry in files:
        parts = entry.parts
        if parts[0] == "..":
            if entry.name in scripts:
                continue
            return False
        if "__pycache__" in parts or entry.suffix == ".pyc":
            continue
        if parts[0].endswith(".dist-info"):
            dist_info = parts[0]
            if len(parts) == 2 and parts[1] in _REGENERATED_METADATA:
                continue
        entries.append("/".join(parts))
    if dist_info is None:
        return False
    pythons = ".".join(sorted({tag.split("-", 1)[0] for tag in tags}))
    name = re.sub(r"[-_.]+", "_", distribution.metadata["Name"]).lower()
    target = wheelhouse / f"{name}-{distribution.version}-{pythons}-none-any.whl"
    temporary = target.with_suffix(".tmp")
    records = []
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
        for relative in sorted(entries):
            data = (base / relative).read_bytes()
            archive.writestr(_zip_entry(relative), data)
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest())
            records.append(
                f"{relative},sha256={digest.rstrip(b'=').decode()},{len(data)}"
            )
        records.append(f"{dist_info}/RECORD,,")
        archive.writestr(_zip_entry(f"{dist_info}/RECORD"), "\n".join(records) + "\n")
    temporary.replace(target)
    return True


def _zip_entry(name: str) -> zipfile.ZipInfo:
    entry = zipfile.ZipInfo(name, _ZIP_TIMESTAMP)
    entry.compress_type = zipfile.ZIP_DEFLATED
    entry.external_attr = 0o644 << 16
    return entry


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


def _launcher(
    topology_name: str,
    *,
    offline: bool = False,
    mode: str = "runtime",
    edition: str = "eclab",
) -> str:
    if mode == "lean":
        return f"""#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${{BASH_SOURCE[0]}}")" && pwd)"
cd "$root"
if [[ "${{1-}}" == --eclab-build-venv ]]; then
    echo "lean archive does not include a Python runtime to build" >&2
    exit 2
fi
if [[ $# -eq 0 ]]; then set -- deploy -t {shlex.quote(topology_name)}; fi
if [[ -x "$root/.eclab-check-host-requirements.sh" ]]; then
    "$root/.eclab-check-host-requirements.sh" "$@"
fi
exec {shlex.quote(edition)} "$@"
"""
    if offline:
        script_name = hashlib.sha256(edition.encode("utf-8")).hexdigest() + ".py"
        return f"""#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${{BASH_SOURCE[0]}}")" && pwd)"
runtime="$root/.eclab-venv"
containerlab="$root/tools/containerlab/bin/containerlab"
vrnetlab="$root/tools/vrnetlab"
if [[ "${{1-}}" == --eclab-build-venv ]]; then
    if [[ $# -ne 1 ]]; then
        echo "--eclab-build-venv does not take lab operation arguments" >&2
        exit 2
    fi
    if [[ -x "$runtime/bin/python" ]]; then
        echo "offline Python environment is already bundled"
        exit 0
    fi
    echo "offline Python environment is missing" >&2
    exit 1
fi
if [[ ! -x "$runtime/bin/python" || ! -f "$runtime/bin/{edition}" ]]; then
    echo "offline {edition} runtime is incomplete" >&2
    exit 1
fi
if [[ ! -x "$containerlab" ]]; then
    echo "offline Containerlab executable is missing" >&2
    exit 1
fi
export CONTAINERLAB_BIN="$containerlab"
export CONTAINERLAB_UPDATE=0
unset CONTAINERLAB_VERSION VRNETLAB_VERSION
export PATH="$(dirname -- "$containerlab"):$PATH"
if [[ -d "$vrnetlab" ]]; then
    export VRNETLAB_DIR="$vrnetlab"
    export VRNETLAB_UPDATE=0
fi
if [[ $# -eq 0 ]]; then set -- deploy -t {shlex.quote(topology_name)}; fi
if [[ -x "$root/.eclab-check-host-requirements.sh" ]]; then
    "$root/.eclab-check-host-requirements.sh" "$@"
fi
if [[ -f "$runtime/bin/.eclab-frozen-scripts/{script_name}" ]]; then
    exec "$runtime/bin/{edition}" "$@"
fi
exec "$runtime/bin/python" "$runtime/bin/{edition}" "$@"
"""
    return f"""#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${{BASH_SOURCE[0]}}")" && pwd)"
requirements="$root/requirements.freeze.txt"
wheelhouse="$root/wheelhouse"
venv="$root/.eclab-venv"
prepare_only=0
if [[ "${{1-}}" == --eclab-build-venv ]]; then
    if [[ $# -ne 1 ]]; then
        echo "--eclab-build-venv does not take lab operation arguments" >&2
        exit 2
    fi
    prepare_only=1
    set --
fi
if [[ ! -x "$venv/bin/{edition}" || ! -x "$venv/bin/python" || ! -x "$venv/bin/containerlab" || ! -f "$root/.eclab-freeze.env" ]]; then
    python=""
    for candidate in ${{ECLAB_PYTHON:-}} python3 $(sed 's/^/python/' "$root/{PYTHON_VERSIONS_NAME}"); do
        command -v "$candidate" >/dev/null 2>&1 || continue
        version="$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])')" || continue
        if grep -qxF "$version" "$root/{PYTHON_VERSIONS_NAME}"; then
            python="$candidate"
            break
        fi
    done
    if [[ -z "$python" ]]; then
        echo "no supported Python found; install one of: $(tr '\\n' ' ' < "$root/{PYTHON_VERSIONS_NAME}")or set ECLAB_PYTHON" >&2
        exit 1
    fi
    rm -rf "$venv" "$root/.eclab-freeze.env"
    if ! {{
        "$python" -m venv "$venv" &&
        "$venv/bin/python" -m pip install --no-index --find-links "$wheelhouse" -r "$requirements" &&
        "$venv/bin/python" -m engulf_clab_freeze.runtime prepare "$root"
    }}; then
        rm -rf "$venv" "$root/.eclab-freeze.env"
        echo "could not install the bundled {edition} runtime" >&2
        exit 1
    fi
fi
source "$root/.eclab-freeze.env"
unset CONTAINERLAB_VERSION VRNETLAB_VERSION
"$venv/bin/python" -m engulf_clab_freeze.runtime verify "$root"
if [[ "$prepare_only" -eq 1 ]]; then
    echo "prepared .eclab-venv"
    exit 0
fi
if [[ $# -eq 0 ]]; then set -- deploy -t {shlex.quote(topology_name)}; fi
if [[ -x "$root/.eclab-check-host-requirements.sh" ]]; then
    "$root/.eclab-check-host-requirements.sh" "$@"
fi
for argument in "$@"; do
    case "$argument" in
        --eclab-containerlab-bin|--eclab-containerlab-bin=*|--eclab-containerlab-dir|--eclab-containerlab-dir=*|--eclab-containerlab-repo|--eclab-containerlab-repo=*|--eclab-containerlab-version|--eclab-containerlab-version=*|--eclab-containerlab-update|--eclab-vrnetlab-dir|--eclab-vrnetlab-dir=*|--eclab-vrnetlab-repo|--eclab-vrnetlab-repo=*|--eclab-vrnetlab-version|--eclab-vrnetlab-version=*|--eclab-vrnetlab-update)
            echo "runtime archive rejects tool overrides" >&2
            exit 1
            ;;
    esac
done
runner="$venv/bin/{edition}"
exec "$runner" "$@"
"""
