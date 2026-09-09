"""Install the packaged eclab demonstration lab."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import time
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import NoReturn

BUNDLE_FORMAT = 2
DISTRIBUTION_VERSION = "0.5.0"
DEFAULT_DIRECTORY = "eclab-demo-lab"
MARKER = ".eclab-demo-lab.json"
REPLACEABLE_BUNDLE_FORMATS = frozenset({1, BUNDLE_FORMAT})


def fail(message: str) -> NoReturn:
    raise SystemExit(f"error: {message}")


def bundled_lab() -> Traversable:
    bundle = resources.files("engulf_clab_demo_lab").joinpath("bundle")
    if bundle.is_dir():
        return bundle
    source_bundle = Path(__file__).resolve().parents[2] / "bundle"
    if source_bundle.is_dir():
        return source_bundle
    fail("the installed distribution does not contain its demo bundle")


def _copy_tree(source: Traversable, destination: Path) -> None:
    destination.mkdir(mode=0o755)
    for child in source.iterdir():
        target = destination / child.name
        if child.is_dir():
            _copy_tree(child, target)
        elif child.is_file():
            with child.open("rb") as source_file, target.open("xb") as target_file:
                shutil.copyfileobj(source_file, target_file)


def _hashes(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink() and path.name != MARKER:
            relative = path.relative_to(root).as_posix()
            if (
                relative.startswith(("artifacts/", ".eclab/", ".eclab-venv/", "clab-"))
                or (
                    path.parent == root
                    and path.name.startswith(".engulf-clab-lab-")
                    and path.name.endswith((".clab.yml", ".clab.yaml"))
                )
            ):
                continue
            result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _read_marker(target: Path) -> dict[str, object] | None:
    marker = target / MARKER
    if target.is_symlink() or not target.is_dir() or marker.is_symlink() or not marker.is_file():
        return None
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(value, dict)
        or value.get("distribution") != "engulf-clab-demo-lab"
        or value.get("format") not in REPLACEABLE_BUNDLE_FORMATS
    ):
        return None
    return value


def _write_marker(target: Path) -> None:
    marker = {
        "format": BUNDLE_FORMAT,
        "distribution": "engulf-clab-demo-lab",
        "version": DISTRIBUTION_VERSION,
        "files": _hashes(target),
    }
    (target / MARKER).write_text(
        json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _check(target: Path) -> None:
    marker = _read_marker(target)
    if marker is None:
        fail(f"{target} is not a recognized eclab demo-lab installation")
    if marker.get("version") != DISTRIBUTION_VERSION:
        fail(
            f"{target} was installed by version {marker.get('version')!r}, "
            f"not {DISTRIBUTION_VERSION}"
        )
    expected = marker.get("files")
    if not isinstance(expected, dict) or expected != _hashes(target):
        fail(f"packaged files below {target} have changed")
    artifacts = target / "artifacts"
    if artifacts.is_symlink() or not artifacts.is_dir():
        fail(f"missing generated-artifact directory: {artifacts}")


def _prepare_installation(target: Path) -> None:
    (target / "artifacts").mkdir(mode=0o755)
    (target / "run-eclab.sh").chmod(0o755)
    (target / "prepare-archive.sh").chmod(0o755)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="eclab-demo-lab-install", description=__doc__)
    result.add_argument("destination", nargs="?", type=Path, default=Path(DEFAULT_DIRECTORY))
    result.add_argument("--check", action="store_true")
    result.add_argument("--replace", action="store_true")
    result.add_argument("--backup-dir", type=Path)
    return result


def main() -> int:
    arguments = parser().parse_args()
    expanded_target = arguments.destination.expanduser()
    target = Path(os.path.abspath(expanded_target))
    parent = target.parent
    if arguments.check:
        if arguments.replace:
            fail("--check cannot be combined with --replace")
        _check(target)
        print(f"{target} is a current eclab demo-lab installation")
        return 0
    if target.is_symlink():
        fail(f"destination must not be a symlink: {target}")
    if parent.is_symlink() or not parent.is_dir():
        fail(f"destination parent must be an existing non-symlink directory: {parent}")
    if target.exists() and not arguments.replace:
        if _read_marker(target) is None:
            fail(f"refusing to replace unrecognized path: {target}")
        _check(target)
        print(f"{target} is already installed and current")
        return 0
    staging = parent / f".{target.name}.installing-{os.getpid()}"
    if staging.exists() or staging.is_symlink():
        fail(f"temporary installation path already exists: {staging}")
    previous: Path | None = None
    try:
        _copy_tree(bundled_lab(), staging)
        _prepare_installation(staging)
        _write_marker(staging)
        if target.exists() or target.is_symlink():
            if target.is_symlink() or _read_marker(target) is None:
                fail(f"refusing to replace unrecognized path: {target}")
            backup_root = (
                arguments.backup_dir.expanduser().resolve()
                if arguments.backup_dir is not None
                else parent / f".{target.name}-backups"
            )
            if backup_root.is_symlink():
                fail(f"backup directory must not be a symlink: {backup_root}")
            backup_root.mkdir(parents=True, exist_ok=True)
            previous = backup_root / f"{target.name}-{os.getpid()}-{time.time_ns()}"
            target.replace(previous)
        try:
            staging.replace(target)
        except BaseException:
            if previous is not None and not target.exists():
                previous.replace(target)
            raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    if previous is not None:
        print(f"backed up the previous installation to {previous}")
    print(f"installed the eclab demo lab to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
