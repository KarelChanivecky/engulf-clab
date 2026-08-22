from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from engulf_api import StateStore
from engulf_clab_schema_api import ContainerlabSourceHint, ContainerlabSourceKind

SCHEMA_RELATIVE = Path("schemas/clab.schema.json")
DEFAULT_REPOSITORY = "https://github.com/KarelChanivecky/containerlab"
DEFAULT_REVISION = "ft_fgt_license_support"


class SchemaSourceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BaseSchema:
    document: dict[str, object]
    content: bytes
    source_kind: str
    repository: str | None
    revision: str | None
    version: str | None
    dirty: bool
    sha256: str


def source_hint_from_environment(
    environment: Mapping[str, str],
    *,
    binary: str | Path | None = None,
) -> ContainerlabSourceHint:
    configured_binary = environment.get("CONTAINERLAB_BIN", "").strip()
    if configured_binary:
        return ContainerlabSourceHint(
            ContainerlabSourceKind.BINARY,
            binary=Path(configured_binary).expanduser().resolve(),
        )
    configured_checkout = environment.get("CONTAINERLAB_DIR", "").strip()
    if configured_checkout:
        return ContainerlabSourceHint(
            ContainerlabSourceKind.CHECKOUT,
            checkout=Path(configured_checkout).expanduser().resolve(),
        )
    if binary is not None:
        candidate = Path(binary).expanduser()
        if candidate.is_absolute() or candidate.parent != Path("."):
            return ContainerlabSourceHint(
                ContainerlabSourceKind.BINARY,
                binary=candidate.resolve(),
            )
        if resolved := shutil.which(str(binary)):
            return ContainerlabSourceHint(
                ContainerlabSourceKind.BINARY,
                binary=Path(resolved).resolve(),
            )
    if resolved := shutil.which("containerlab"):
        return ContainerlabSourceHint(
            ContainerlabSourceKind.BINARY,
            binary=Path(resolved).resolve(),
        )
    configured_repository = environment.get("CONTAINERLAB_REPO", "").strip()
    repository, revision = split_repository_revision(configured_repository or DEFAULT_REPOSITORY)
    explicit_revision = environment.get("CONTAINERLAB_VERSION", "").strip()
    return ContainerlabSourceHint(
        ContainerlabSourceKind.REPOSITORY,
        repository=repository,
        revision=(
            explicit_revision
            or revision
            or ("HEAD" if configured_repository else DEFAULT_REVISION)
        ),
    )


def resolve_base_schema(
    state: StateStore,
    environment: Mapping[str, str],
    hint: ContainerlabSourceHint,
    *,
    refresh: bool = False,
) -> BaseSchema:
    if hint.kind is ContainerlabSourceKind.CHECKOUT:
        if hint.checkout is None:
            raise SchemaSourceError("checkout source hint has no checkout path")
        return _from_checkout(state, hint.checkout)
    if hint.kind is ContainerlabSourceKind.BINARY:
        if override := environment.get("CONTAINERLAB_SCHEMA", "").strip():
            return _from_local_override(Path(override).expanduser().resolve(), hint.binary)
        if hint.binary is None:
            raise SchemaSourceError("binary source hint has no executable path")
        checkout = checkout_for_binary(hint.binary)
        if checkout is not None:
            return _from_checkout(state, checkout)
        return _from_binary(state, hint.binary)
    if hint.repository is None or hint.revision is None:
        raise SchemaSourceError("repository source hint is incomplete")
    content, resolved_revision = _fetch_schema(
        state, hint.repository, hint.revision, refresh=refresh
    )
    return _base(
        content,
        source_kind="repository",
        repository=sanitize_repository(hint.repository),
        revision=resolved_revision,
    )


def checkout_for_binary(binary: Path) -> Path | None:
    candidate = binary.resolve()
    for parent in (candidate.parent, *candidate.parents):
        if (parent / "go.mod").is_file() and (parent / "schemas").is_dir():
            return parent
    return None


def split_repository_revision(repository: str) -> tuple[str, str | None]:
    marker = "/tree/"
    if marker in repository:
        base, revision = repository.split(marker, 1)
        if base.startswith("https://github.com/") and revision:
            return base, revision
    return repository, None


def sanitize_repository(repository: str) -> str:
    parts = urlsplit(repository)
    if not parts.scheme or not parts.netloc:
        return repository
    host = parts.hostname or ""
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def _from_checkout(state: StateStore, checkout: Path) -> BaseSchema:
    if not checkout.is_dir():
        raise SchemaSourceError(f"Containerlab checkout does not exist: {checkout}")
    repository = _git(checkout, ("remote", "get-url", "origin"), required=False)
    revision = _git(checkout, ("rev-parse", "HEAD"), required=False)
    schema_path = checkout / SCHEMA_RELATIVE
    if schema_path.is_file() and not schema_path.is_symlink():
        try:
            content = schema_path.read_bytes()
        except OSError:
            content = None
        if content is not None:
            dirty = bool(
                _git(
                    checkout,
                    ("status", "--porcelain", "--", SCHEMA_RELATIVE.as_posix()),
                    required=False,
                )
            )
            return _base(
                content,
                source_kind="checkout",
                repository=None if repository is None else sanitize_repository(repository),
                revision=revision,
                dirty=dirty,
            )
    if revision is not None:
        committed = _git_bytes(
            checkout,
            ("show", f"{revision}:{SCHEMA_RELATIVE.as_posix()}"),
            required=False,
        )
        if committed is not None:
            return _base(
                committed,
                source_kind="checkout-commit",
                repository=None if repository is None else sanitize_repository(repository),
                revision=revision,
            )
    if repository is not None and revision is not None:
        content, _ = _fetch_schema(state, repository, revision)
        return _base(
            content,
            source_kind="checkout-fetch",
            repository=sanitize_repository(repository),
            revision=revision,
        )
    raise SchemaSourceError("selected Containerlab checkout has no usable exact schema")


def _from_local_override(path: Path, binary: Path | None) -> BaseSchema:
    if not path.is_file() or path.is_symlink():
        raise SchemaSourceError(f"CONTAINERLAB_SCHEMA is not a regular file: {path}")
    version: str | None = None
    repository: str | None = None
    revision: str | None = None
    if binary is not None and binary.is_file():
        try:
            metadata = _binary_metadata(binary)
        except SchemaSourceError:
            metadata = {}
        version = _string(metadata.get("version"))
        repository = _string(metadata.get("repository"))
        revision = _string(metadata.get("commit"))
    return _base(
        path.read_bytes(),
        source_kind="binary-override",
        repository=None if repository is None else sanitize_repository(repository),
        revision=revision,
        version=version,
    )


def _from_binary(state: StateStore, binary: Path) -> BaseSchema:
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise SchemaSourceError(f"Containerlab binary is not executable: {binary}")
    metadata = _binary_metadata(binary)
    repository = _string(metadata.get("repository"))
    revision = _string(metadata.get("commit"))
    version = _string(metadata.get("version"))
    if revision in {None, "", "none", "unknown"}:
        revision = None if version is None else f"v{version.removeprefix('v')}"
    if repository is None or revision is None:
        raise SchemaSourceError(
            "Containerlab binary does not report an exact repository revision; "
            "set CONTAINERLAB_SCHEMA"
        )
    content, resolved_revision = _fetch_schema(state, repository, revision)
    return _base(
        content,
        source_kind="binary",
        repository=sanitize_repository(repository),
        revision=resolved_revision,
        version=version,
    )


def _binary_metadata(binary: Path) -> dict[str, object]:
    try:
        process = subprocess.run(
            [str(binary), "version", "--json"],
            check=True,
            capture_output=True,
            timeout=15,
        )
        value = json.loads(process.stdout.decode("utf-8"))
    except (OSError, subprocess.SubprocessError, UnicodeError, json.JSONDecodeError) as error:
        raise SchemaSourceError(f"failed to read Containerlab version metadata: {error}") from error
    if not isinstance(value, dict):
        raise SchemaSourceError("Containerlab version metadata is not an object")
    return value


def _fetch_schema(
    state: StateStore,
    repository: str,
    revision: str,
    *,
    refresh: bool = False,
) -> tuple[bytes, str]:
    repository, embedded_revision = split_repository_revision(repository)
    selected_revision = revision or embedded_revision
    if selected_revision is None:
        raise SchemaSourceError("Containerlab repository source has no revision")
    key = hashlib.sha256(
        f"{sanitize_repository(repository)}\0{selected_revision}".encode()
    ).hexdigest()
    cache_root = state.directory / "containerlab-schemas"
    cache_root.mkdir(parents=True, exist_ok=True)
    cached = cache_root / f"{key}.json"
    cached_revision = cache_root / f"{key}.revision"
    if not refresh and cached.is_file() and cached_revision.is_file():
        content = cached.read_bytes()
        _parse_schema(content)
        resolved = cached_revision.read_text(encoding="utf-8").strip()
        if resolved:
            return content, resolved
    repository_cache = cache_root / f"{key}.git"
    try:
        if not repository_cache.is_dir():
            subprocess.run(
                ["git", "init", "--bare", str(repository_cache)],
                check=True,
                capture_output=True,
                timeout=30,
            )
        subprocess.run(
            [
                "git",
                "-C",
                str(repository_cache),
                "fetch",
                "--depth",
                "1",
                repository,
                selected_revision,
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
        process = subprocess.run(
            [
                "git",
                "-C",
                str(repository_cache),
                "show",
                f"FETCH_HEAD:{SCHEMA_RELATIVE.as_posix()}",
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise SchemaSourceError(
            f"failed to fetch Containerlab schema at {selected_revision} from "
            f"{sanitize_repository(repository)}"
        ) from error
    content = process.stdout
    resolved_revision = _git(repository_cache, ("rev-parse", "FETCH_HEAD"), required=True)
    assert resolved_revision is not None
    _parse_schema(content)
    temporary = cached.with_suffix(".tmp")
    temporary.write_bytes(content)
    temporary.replace(cached)
    temporary_revision = cached_revision.with_suffix(".tmp")
    temporary_revision.write_text(resolved_revision + "\n", encoding="utf-8")
    temporary_revision.replace(cached_revision)
    return content, resolved_revision


def _base(
    content: bytes,
    *,
    source_kind: str,
    repository: str | None,
    revision: str | None,
    version: str | None = None,
    dirty: bool = False,
) -> BaseSchema:
    document = _parse_schema(content)
    return BaseSchema(
        document,
        content,
        source_kind,
        repository,
        revision,
        version,
        dirty,
        hashlib.sha256(content).hexdigest(),
    )


def _parse_schema(content: bytes) -> dict[str, object]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise SchemaSourceError(f"Containerlab schema is invalid JSON: {error}") from error
    if not isinstance(value, dict) or not isinstance(value.get("properties"), dict):
        raise SchemaSourceError("Containerlab schema must be an object with properties")
    return value


def _git(checkout: Path, arguments: Sequence[str], *, required: bool) -> str | None:
    content = _git_bytes(checkout, arguments, required=required)
    return None if content is None else content.decode("utf-8").strip()


def _git_bytes(checkout: Path, arguments: Sequence[str], *, required: bool) -> bytes | None:
    try:
        process = subprocess.run(
            ["git", "-C", str(checkout), *arguments],
            check=True,
            capture_output=True,
            timeout=20,
        )
        return process.stdout
    except (OSError, subprocess.SubprocessError) as error:
        if required:
            raise SchemaSourceError(f"git {' '.join(arguments)} failed") from error
        return None


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
