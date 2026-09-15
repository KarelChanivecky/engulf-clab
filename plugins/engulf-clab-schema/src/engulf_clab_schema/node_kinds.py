from __future__ import annotations

import hashlib
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from engulf_api import StateStore
from engulf_clab_schema_api import (
    ContainerlabSourceHint,
    ContainerlabSourceKind,
    VrnetlabSourceHint,
)

from .source import BaseSchema, checkout_for_binary, sanitize_repository, split_repository_revision

DEFAULT_VRNETLAB_REPOSITORY = (
    "https://github.com/KarelChanivecky/vrnetlab/tree/master"
)
NODE_KIND_PROVIDER_ID = "containerlab.node_kinds"
_CONTAINERLAB_KIND_INDEX = PurePosixPath("docs/manual/kinds/index.md")
_README_NAMES = frozenset({"readme", "readme.md", "readme.markdown", "readme.txt"})
_KIND_LINK = re.compile(
    r"\|\s*\*\*(?P<label>[^*]+)\*\*\s*\|\s*\[`(?P<kind>[^`]+)`\]"
    r"\((?P<path>[^)#]+\.md)(?:#[^)]+)?\)",
    re.IGNORECASE,
)
_SAFE_KIND = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")

# Containerlab and vrnetlab do not publish a machine-readable relationship.
# Keep only non-obvious exceptions here; exact normalized vendor/product matches
# are discovered without a table.
_VRNETLAB_EXCEPTIONS = {
    "mikrotik_ros": "mikrotik/routeros/README.md",
    "paloalto_panos": "paloalto/pan/README.md",
    "f5_bigip-ve": "f5_bigip/README.md",
    "sonic-vm": "sonic/README.md",
}


class NodeKindSourceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    kind: str
    repository: str | None
    revision: str | None
    dirty: bool
    sha256: str


@dataclass(frozen=True, slots=True)
class NodeKindRecord:
    kind: str
    summary: str
    containerlab_path: str | None
    containerlab_content: bytes | None
    vrnetlab_path: str | None
    vrnetlab_content: bytes | None


@dataclass(frozen=True, slots=True)
class NodeKindCatalog:
    containerlab: SourceIdentity
    vrnetlab: SourceIdentity
    kinds: tuple[NodeKindRecord, ...]


@dataclass(frozen=True, slots=True)
class _RepositoryView:
    kind: str
    repository: str | None
    revision: str | None
    dirty: bool
    paths: tuple[str, ...]
    root: Path | None = None
    git_directory: Path | None = None

    def read(self, path: str) -> bytes | None:
        candidate = PurePosixPath(path)
        if candidate.is_absolute() or ".." in candidate.parts or path not in self.paths:
            return None
        if self.root is not None:
            source = self.root.joinpath(*candidate.parts)
            if not source.is_file() or source.is_symlink():
                return None
            try:
                return source.read_bytes()
            except OSError:
                return None
        if self.git_directory is None or self.revision is None:
            return None
        return _git_bytes(
            self.git_directory,
            ("show", f"{self.revision}:{candidate.as_posix()}"),
            bare=True,
            required=False,
        )


def resolve_node_kind_catalog(
    state: StateStore,
    environment: Mapping[str, str],
    base: BaseSchema,
    containerlab_hint: ContainerlabSourceHint,
    vrnetlab_hint: VrnetlabSourceHint | None = None,
    *,
    refresh: bool = False,
) -> NodeKindCatalog:
    containerlab = _containerlab_view(state, base, containerlab_hint)
    vrnetlab = _vrnetlab_view(state, environment, vrnetlab_hint, refresh=refresh)
    kinds = _schema_kinds(base.document)
    index_content = containerlab.read(_CONTAINERLAB_KIND_INDEX.as_posix())
    index = _kind_document_index(index_content)
    vrnetlab_readmes = _vrnetlab_readmes(vrnetlab.paths)
    records: list[NodeKindRecord] = []
    for kind in kinds:
        label, documentation = index.get(kind, (_display_name(kind), None))
        containerlab_path = _containerlab_document(containerlab.paths, kind, documentation)
        vrnetlab_path = _vrnetlab_document(kind, vrnetlab_readmes)
        records.append(
            NodeKindRecord(
                kind,
                label,
                containerlab_path,
                None if containerlab_path is None else containerlab.read(containerlab_path),
                vrnetlab_path,
                None if vrnetlab_path is None else vrnetlab.read(vrnetlab_path),
            )
        )
    return NodeKindCatalog(
        _identity(containerlab, _relevant_containerlab_content(containerlab, records)),
        _identity(vrnetlab, _relevant_vrnetlab_content(vrnetlab, records)),
        tuple(records),
    )


def vrnetlab_source_hint_from_environment(
    environment: Mapping[str, str],
) -> VrnetlabSourceHint:
    if configured := environment.get("VRNETLAB_DIR", "").strip():
        return VrnetlabSourceHint(checkout=Path(configured).expanduser().resolve())
    repository, embedded = split_repository_revision(
        environment.get("VRNETLAB_REPO", DEFAULT_VRNETLAB_REPOSITORY)
    )
    revision = environment.get("VRNETLAB_VERSION", "").strip() or embedded
    return VrnetlabSourceHint(repository=repository, revision=revision)


def _containerlab_view(
    state: StateStore,
    base: BaseSchema,
    hint: ContainerlabSourceHint,
) -> _RepositoryView:
    checkout: Path | None = None
    if hint.kind is ContainerlabSourceKind.CHECKOUT:
        checkout = hint.checkout
    elif hint.kind is ContainerlabSourceKind.BINARY and hint.binary is not None:
        checkout = checkout_for_binary(hint.binary)
    if checkout is not None:
        return _checkout_view(checkout, label="Containerlab")
    if base.repository is None or base.revision is None:
        raise NodeKindSourceError(
            "selected Containerlab source has no repository revision for node-kind guidance"
        )
    return _remote_view(
        state, "containerlab", base.repository, base.revision, refresh=False
    )


def _vrnetlab_view(
    state: StateStore,
    environment: Mapping[str, str],
    hint: VrnetlabSourceHint | None,
    *,
    refresh: bool,
) -> _RepositoryView:
    selected = hint or vrnetlab_source_hint_from_environment(environment)
    if selected.checkout is not None and _valid_vrnetlab_checkout(selected.checkout):
        return _checkout_view(selected.checkout, label="vrnetlab")
    configured = environment.get("VRNETLAB_DIR", "").strip()
    if configured:
        candidate = Path(configured).expanduser().resolve()
        if _valid_vrnetlab_checkout(candidate):
            return _checkout_view(candidate, label="vrnetlab")
    managed = state.path("vrnetlab")
    if _valid_vrnetlab_checkout(managed):
        return _checkout_view(managed, label="vrnetlab")
    repository = selected.repository
    revision = selected.revision
    if repository is None:
        repository, embedded = split_repository_revision(
            environment.get("VRNETLAB_REPO", DEFAULT_VRNETLAB_REPOSITORY)
        )
        revision = environment.get("VRNETLAB_VERSION", "").strip() or embedded
    if repository is None:
        raise NodeKindSourceError("vrnetlab source selection has no repository")
    return _remote_view(
        state,
        "vrnetlab",
        repository,
        revision or "HEAD",
        refresh=refresh,
    )


def _checkout_view(checkout: Path, *, label: str) -> _RepositoryView:
    if not checkout.is_dir():
        raise NodeKindSourceError(f"selected {label} checkout does not exist: {checkout}")
    paths = _checkout_paths(checkout)
    repository = _git(checkout, ("remote", "get-url", "origin"), required=False)
    revision = _git(checkout, ("rev-parse", "HEAD"), required=False)
    dirty = bool(_git(checkout, ("status", "--porcelain"), required=False))
    return _RepositoryView(
        "checkout",
        None if repository is None else sanitize_repository(repository),
        revision,
        dirty,
        paths,
        root=checkout,
    )


def _remote_view(
    state: StateStore,
    label: str,
    repository: str,
    revision: str,
    *,
    refresh: bool = True,
) -> _RepositoryView:
    repository, embedded = split_repository_revision(repository)
    selected_revision = revision or embedded or "HEAD"
    sanitized = sanitize_repository(repository)
    key = hashlib.sha256(sanitized.encode()).hexdigest()
    root = state.directory / "node-kind-repositories"
    root.mkdir(parents=True, exist_ok=True)
    git_directory = root / f"{label}-{key}.git"
    reference_key = hashlib.sha256(selected_revision.encode()).hexdigest()
    cache_reference = f"refs/engulf-clab/node-kinds/{reference_key}"
    cached_commit = (
        None
        if refresh or not git_directory.is_dir()
        else _git(git_directory, ("rev-parse", "--verify", cache_reference), bare=True, required=False)
    )
    try:
        if not git_directory.is_dir():
            subprocess.run(
                ["git", "init", "--bare", str(git_directory)],
                check=True,
                capture_output=True,
                timeout=30,
            )
        if cached_commit is None:
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(git_directory),
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
    except (OSError, subprocess.SubprocessError) as error:
        raise NodeKindSourceError(
            f"failed to fetch {label} node-kind guidance from {sanitized} at {selected_revision}"
        ) from error
    commit = cached_commit or _git(
        git_directory, ("rev-parse", "FETCH_HEAD"), bare=True, required=True
    )
    assert commit is not None
    if cached_commit is None:
        _git(
            git_directory,
            ("update-ref", cache_reference, commit),
            bare=True,
            required=True,
        )
    listing = _git_bytes(
        git_directory,
        ("ls-tree", "-r", "--name-only", commit),
        bare=True,
        required=True,
    )
    assert listing is not None
    paths = tuple(
        line for line in listing.decode("utf-8").splitlines() if line and ".." not in PurePosixPath(line).parts
    )
    return _RepositoryView("repository", sanitized, commit, False, paths, git_directory=git_directory)


def _schema_kinds(document: Mapping[str, object]) -> tuple[str, ...]:
    definitions = document.get("definitions")
    node_config = definitions.get("node-config") if isinstance(definitions, dict) else None
    properties = node_config.get("properties") if isinstance(node_config, dict) else None
    kind = properties.get("kind") if isinstance(properties, dict) else None
    values = kind.get("enum") if isinstance(kind, dict) else None
    if not isinstance(values, list):
        return ()
    return tuple(
        sorted({value for value in values if isinstance(value, str) and _SAFE_KIND.fullmatch(value)})
    )


def _kind_document_index(content: bytes | None) -> dict[str, tuple[str, str]]:
    if content is None:
        return {}
    try:
        text = content.decode("utf-8")
    except UnicodeError:
        return {}
    result: dict[str, tuple[str, str]] = {}
    for match in _KIND_LINK.finditer(text):
        kind = match.group("kind")
        path = PurePosixPath("docs/manual/kinds", match.group("path")).as_posix()
        result.setdefault(kind, (match.group("label").strip(), path))
    return result


def _containerlab_document(
    paths: Sequence[str], kind: str, indexed: str | None
) -> str | None:
    available = set(paths)
    candidates = [indexed] if indexed is not None else []
    candidates.extend(
        [
            f"docs/manual/kinds/{kind}.md",
            f"docs/manual/kinds/{kind.replace('_', '-')}.md",
        ]
    )
    return next((candidate for candidate in candidates if candidate in available), None)


def _vrnetlab_readmes(paths: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        path
        for path in paths
        if PurePosixPath(path).name.lower() in _README_NAMES
        and len(PurePosixPath(path).parts) <= 3
        and PurePosixPath(path).parts[0] not in {"common", "docs"}
    )


def _vrnetlab_document(kind: str, readmes: Sequence[str]) -> str | None:
    available = set(readmes)
    explicit = _VRNETLAB_EXCEPTIONS.get(kind)
    if explicit in available:
        return explicit
    normalized_kind = _normalized(kind)
    candidates: list[str] = []
    for path in readmes:
        parts = PurePosixPath(path).parts[:-1]
        if not parts:
            continue
        combined = _normalized("".join(parts))
        product = _normalized(parts[-1])
        if combined == normalized_kind or (product == normalized_kind and len(parts) == 1):
            candidates.append(path)
            continue
        if len(parts) >= 2:
            vendor_product = _normalized(parts[-2] + parts[-1])
            if vendor_product == normalized_kind:
                candidates.append(path)
    return candidates[0] if len(candidates) == 1 else None


def _display_name(kind: str) -> str:
    return kind.replace("_", " ").replace("-", " ").title()


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _relevant_containerlab_content(
    view: _RepositoryView, records: Sequence[NodeKindRecord]
) -> tuple[tuple[str, bytes], ...]:
    paths = {_CONTAINERLAB_KIND_INDEX.as_posix()}
    paths.update(item.containerlab_path for item in records if item.containerlab_path is not None)
    return _content(view, paths)


def _relevant_vrnetlab_content(
    view: _RepositoryView, records: Sequence[NodeKindRecord]
) -> tuple[tuple[str, bytes], ...]:
    return _content(
        view, {item.vrnetlab_path for item in records if item.vrnetlab_path is not None}
    )


def _content(view: _RepositoryView, paths: set[str]) -> tuple[tuple[str, bytes], ...]:
    result: list[tuple[str, bytes]] = []
    for path in sorted(paths):
        content = view.read(path)
        if content is not None:
            result.append((path, content))
    return tuple(result)


def _identity(
    view: _RepositoryView, content: Sequence[tuple[str, bytes]]
) -> SourceIdentity:
    digest = hashlib.sha256()
    for path, value in content:
        digest.update(path.encode())
        digest.update(b"\0")
        digest.update(value)
        digest.update(b"\0")
    return SourceIdentity(
        view.kind,
        view.repository,
        view.revision,
        view.dirty,
        digest.hexdigest(),
    )


def _valid_vrnetlab_checkout(path: Path) -> bool:
    return path.is_dir() and (path / "common" / "vrnetlab.py").is_file()


def _checkout_paths(checkout: Path) -> tuple[str, ...]:
    result: list[str] = []
    for current, directories, files in os.walk(checkout, followlinks=False):
        root = Path(current)
        directories[:] = [
            name
            for name in directories
            if name != ".git" and not (root / name).is_symlink()
        ]
        for name in files:
            path = root / name
            if not path.is_symlink():
                result.append(path.relative_to(checkout).as_posix())
    return tuple(sorted(result))


def _git(
    checkout: Path,
    arguments: Sequence[str],
    *,
    bare: bool = False,
    required: bool,
) -> str | None:
    content = _git_bytes(checkout, arguments, bare=bare, required=required)
    return None if content is None else content.decode("utf-8").strip()


def _git_bytes(
    checkout: Path,
    arguments: Sequence[str],
    *,
    bare: bool = False,
    required: bool,
) -> bytes | None:
    command = ["git", "--git-dir", str(checkout)] if bare else ["git", "-C", str(checkout)]
    try:
        process = subprocess.run(
            [*command, *arguments],
            check=True,
            capture_output=True,
            timeout=30,
        )
        return process.stdout
    except (OSError, subprocess.SubprocessError) as error:
        if required:
            raise NodeKindSourceError(f"git {' '.join(arguments)} failed") from error
        return None
