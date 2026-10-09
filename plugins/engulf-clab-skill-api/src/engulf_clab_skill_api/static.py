"""Export packaged, non-generated skills to the shared collector."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType

from engulf_api import AfterGoalAPI, Invocation, StateScope

from .context import (
    SKILL_CONTEXTS,
    record_skill,
    tracked_skill_targets,
)

INSTALL_COMMAND = "install-skills"
SKILL_CONTRIBUTION_CONTEXTS = SKILL_CONTEXTS
_SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_EMPTY_EXTRA_FILES: Mapping[str, bytes] = MappingProxyType({})


def explicit_install(arguments: tuple[str, ...]) -> bool:
    """Return whether arguments request an explicit skill installation."""
    return bool(
        arguments
        and arguments[0] == INSTALL_COMMAND
        and "--help" not in arguments
        and "-h" not in arguments
    )


def skip_contribution(
    arguments: tuple[str, ...],
    environment: Mapping[str, str],
) -> bool:
    """Return whether this invocation should skip automatic contribution."""
    return (
        environment.get("ENGULF_INTERNAL_PROTOCOL") == "1"
        or not arguments
        or arguments[0] == "help"
        or "--help" in arguments
        or "-h" in arguments
    )


def tracked_target_exists(api: AfterGoalAPI, name: str) -> bool:
    """Return whether the collector published a tracked target for ``name``."""
    return any(path.name == name for path in tracked_skill_targets(api))


def contribute_static_skill(
    api: AfterGoalAPI,
    invocation: Invocation,
    *,
    name: str,
    packaged_dir: Path,
    extra_files: Mapping[str, bytes] = _EMPTY_EXTRA_FILES,
) -> Path | None:
    """Export and register a packaged skill when this invocation needs it.

    Calling plugins declare ``SKILL_PATHS_CONTEXT`` and
    ``SKILL_TRACKED_TARGETS_CONTEXT`` in ``context_reads`` and
    ``SKILL_PATHS_CONTEXT`` in ``context_writes``.
    """
    explicit = explicit_install(invocation.arguments)
    if not explicit and (
        skip_contribution(invocation.arguments, invocation.environment)
        or not tracked_target_exists(api, name)
    ):
        return None

    if not isinstance(name, str) or _SKILL_NAME.fullmatch(name) is None:
        raise ValueError(f"invalid skill directory name: {name!r}")
    source = _validate_packaged_dir(packaged_dir)
    files = _validate_extra_files(extra_files)
    fingerprint = _fingerprint(source, files)

    state = api.state(StateScope.USER)
    export_root = state.directory / "skill-export"
    if export_root.is_symlink():
        raise ValueError(f"refusing symlinked skill export root: {export_root}")
    export_root.mkdir(parents=True, exist_ok=True)

    target = export_root / name
    fingerprint_path = export_root / f".{name}.fingerprint.json"
    if target.is_symlink():
        raise ValueError(f"refusing symlinked skill export directory: {target}")
    if fingerprint_path.is_symlink():
        raise ValueError(f"refusing symlinked skill fingerprint: {fingerprint_path}")
    if _export_is_current(target, fingerprint_path, name, fingerprint, files):
        resolved = target.resolve(strict=True)
        record_skill(api, resolved)
        return resolved

    old = export_root / f".{name}.old"
    if old.is_symlink():
        raise ValueError(f"refusing symlinked old skill export: {old}")
    if old.exists():
        if old.is_dir():
            shutil.rmtree(old)
        elif old.is_file():
            old.unlink()
        else:
            raise ValueError(f"refusing unsupported old skill export: {old}")

    staged = Path(tempfile.mkdtemp(prefix=f".{name}.", dir=export_root))
    moved_old = False
    try:
        shutil.copytree(source, staged, dirs_exist_ok=True)
        _write_extra_files(staged, files)
        _validate_export(staged, files)

        if target.is_symlink():
            raise ValueError(f"refusing symlinked skill export directory: {target}")
        if target.exists():
            if not target.is_dir():
                raise ValueError(f"skill export path is not a directory: {target}")
            target.replace(old)
            moved_old = True
        staged.replace(target)
        _write_fingerprint(fingerprint_path, name, fingerprint, export_root)
        resolved = target.resolve(strict=True)
        record_skill(api, resolved)
        if moved_old:
            shutil.rmtree(old)
        return resolved
    except BaseException:
        if target.exists() and not target.is_symlink():
            shutil.rmtree(target)
        if moved_old and old.exists() and not target.exists():
            old.replace(target)
        raise
    finally:
        if staged.exists():
            shutil.rmtree(staged)


def _validate_packaged_dir(packaged_dir: Path) -> Path:
    if not isinstance(packaged_dir, Path):
        raise TypeError("packaged skill directory must be a pathlib.Path")
    if packaged_dir.is_symlink():
        raise ValueError(f"refusing symlinked packaged skill directory: {packaged_dir}")
    source = packaged_dir.resolve(strict=True)
    if not source.is_dir():
        raise ValueError(f"packaged skill source is not a directory: {source}")
    entrypoint = source / "SKILL.md"
    if entrypoint.is_symlink() or not entrypoint.is_file():
        raise ValueError(f"packaged skill source has no regular SKILL.md: {source}")
    for path in source.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"packaged skill source contains a symbolic link: {path}")
        if not path.is_dir() and not path.is_file():
            raise ValueError(f"packaged skill source contains an unsupported entry: {path}")
    return source


def _validate_extra_files(extra_files: Mapping[str, bytes]) -> tuple[tuple[PurePosixPath, bytes], ...]:
    if not isinstance(extra_files, Mapping):
        raise TypeError("extra_files must be a mapping of relative paths to bytes")
    validated: dict[str, tuple[PurePosixPath, bytes]] = {}
    for raw_path, content in extra_files.items():
        if not isinstance(raw_path, str):
            raise TypeError("extra file paths must be strings")
        path = PurePosixPath(raw_path)
        if (
            not raw_path
            or "\x00" in raw_path
            or "\\" in raw_path
            or path.is_absolute()
            or PureWindowsPath(raw_path).is_absolute()
            or PureWindowsPath(raw_path).drive
            or not path.parts
            or ".." in path.parts
        ):
            raise ValueError(f"extra file path must stay inside the skill directory: {raw_path!r}")
        if not isinstance(content, bytes):
            raise TypeError(f"extra file content must be bytes: {raw_path!r}")
        normalized = path.as_posix()
        if normalized in validated:
            raise ValueError(f"duplicate extra file path: {normalized!r}")
        validated[normalized] = (path, content)
    return tuple(validated[key] for key in sorted(validated))


def _fingerprint(source: Path, extra_files: tuple[tuple[PurePosixPath, bytes], ...]) -> str:
    digest = hashlib.sha256()
    records: list[tuple[str, str, int, Path | bytes | None]] = []
    for path in source.rglob("*"):
        relative = path.relative_to(source).as_posix()
        if path.is_symlink():
            raise ValueError(f"packaged skill source contains a symbolic link: {path}")
        if path.is_dir():
            records.append((relative, "D", 0, None))
        elif path.is_file():
            records.append((relative, "F", path.stat().st_size, path))
        else:
            raise ValueError(f"packaged skill source contains an unsupported entry: {path}")
    records.extend(
        (path.as_posix(), "X", len(content), content) for path, content in extra_files
    )
    for relative, kind, size, content in sorted(records, key=lambda item: (item[0], item[1])):
        encoded_path = relative.encode("utf-8")
        digest.update(kind.encode("ascii"))
        digest.update(len(encoded_path).to_bytes(8, "big"))
        digest.update(encoded_path)
        digest.update(size.to_bytes(8, "big"))
        if isinstance(content, Path):
            with content.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
        elif isinstance(content, bytes):
            digest.update(content)
    return digest.hexdigest()


def _export_is_current(
    target: Path,
    fingerprint_path: Path,
    name: str,
    fingerprint: str,
    extra_files: tuple[tuple[PurePosixPath, bytes], ...],
) -> bool:
    if target.is_symlink() or not target.is_dir():
        return False
    if fingerprint_path.is_symlink() or not fingerprint_path.is_file():
        return False
    try:
        metadata = json.loads(fingerprint_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if (
        not isinstance(metadata, dict)
        or metadata.get("skill_name") != name
        or metadata.get("fingerprint") != fingerprint
    ):
        return False
    if not _is_regular_file(target / "SKILL.md"):
        return False
    for relative, _content in extra_files:
        if not _is_regular_file(target.joinpath(*relative.parts)):
            return False
    for path in target.rglob("*"):
        if path.is_symlink() or (not path.is_dir() and not path.is_file()):
            return False
    return True


def _is_regular_file(path: Path) -> bool:
    return not path.is_symlink() and path.is_file()


def _validate_export(
    target: Path,
    extra_files: tuple[tuple[PurePosixPath, bytes], ...],
) -> None:
    if not _is_regular_file(target / "SKILL.md"):
        raise ValueError(f"exported skill has no regular SKILL.md: {target}")
    for relative, _content in extra_files:
        if not _is_regular_file(target.joinpath(*relative.parts)):
            raise ValueError(f"exported extra file is not regular: {relative.as_posix()}")
    for path in target.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"exported skill contains a symbolic link: {path}")
        if not path.is_dir() and not path.is_file():
            raise ValueError(f"exported skill contains an unsupported entry: {path}")


def _write_extra_files(
    target: Path,
    extra_files: tuple[tuple[PurePosixPath, bytes], ...],
) -> None:
    for relative, content in extra_files:
        destination = target.joinpath(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)


def _write_fingerprint(
    path: Path,
    name: str,
    fingerprint: str,
    directory: Path,
) -> None:
    if path.is_symlink():
        raise ValueError(f"refusing symlinked skill fingerprint: {path}")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{name}.fingerprint.",
            suffix=".tmp",
            dir=directory,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(
                {"skill_name": name, "fingerprint": fingerprint},
                stream,
                sort_keys=True,
            )
            stream.write("\n")
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
