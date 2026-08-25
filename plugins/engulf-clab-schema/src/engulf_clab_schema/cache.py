from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import TypeGuard

from engulf_api import ApplicationMetadata
from engulf_clab_schema_api import (
    ECLAB_SCHEMA_PIPELINE_ID,
    CompiledPluginSchema,
    CompiledReference,
    CompiledSchemaBundle,
    ContainerlabSourceHint,
    ContainerlabSourceKind,
    SchemaContribution,
    SchemaPipeline,
    SchemaRegistryEntry,
    VrnetlabSourceHint,
)

from .compiler import COMPILER_VERSION, FORMAT_VERSION
from .source import SCHEMA_RELATIVE, checkout_for_binary

CACHE_FORMAT_VERSION = 2
_README_NAMES = frozenset({"readme", "readme.md", "readme.markdown", "readme.txt"})
_TOP_LEVEL_ARTIFACTS = (
    "manifest.json",
    "clab.schema.json",
    "catalog.json",
    "catalog.md",
)


def schema_input_fingerprint(
    application: ApplicationMetadata,
    entries: Iterable[SchemaRegistryEntry | SchemaContribution],
    containerlab: ContainerlabSourceHint,
    vrnetlab: VrnetlabSourceHint | None,
    environment: Mapping[str, str],
    *,
    pipeline_id: str = ECLAB_SCHEMA_PIPELINE_ID,
    pipeline_lineage: tuple[str, ...] | None = None,
) -> str:
    """Fingerprint cheap inputs that determine a compiled runtime bundle."""
    SchemaPipeline(pipeline_id)
    lineage = (pipeline_id,) if pipeline_lineage is None else pipeline_lineage
    payload = {
        "cache_format": CACHE_FORMAT_VERSION,
        "schema_format": FORMAT_VERSION,
        "compiler": COMPILER_VERSION,
        "application": {
            "application_id": application.application_id,
            "display_name": application.display_name,
            "vendor": application.vendor,
            "product": application.product,
            "short_product_name": application.short_product_name,
            "version": application.version,
        },
        "pipeline": {"id": pipeline_id, "lineage": list(lineage)},
        "plugins": _stable(tuple(entries)),
        "containerlab": _containerlab_input(containerlab, environment),
        "vrnetlab": _vrnetlab_input(vrnetlab, environment),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def cached_bundle_fingerprint(
    root: Path,
    input_fingerprint: str,
    *,
    pipeline_id: str = ECLAB_SCHEMA_PIPELINE_ID,
) -> str | None:
    """Return a complete cached bundle matching the exact cheap-input fingerprint."""
    pipeline_root = _pipeline_root(root, pipeline_id)
    try:
        value = json.loads((pipeline_root / "latest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    if value.get("cache_format") != CACHE_FORMAT_VERSION:
        return None
    if value.get("input_fingerprint") != input_fingerprint:
        return None
    if value.get("pipeline_id") != pipeline_id:
        return None
    fingerprint = value.get("fingerprint")
    if not _fingerprint(fingerprint):
        return None
    target = pipeline_root / "artifacts" / fingerprint
    return (
        fingerprint
        if bundle_directory_complete(target, fingerprint, pipeline_id=pipeline_id)
        else None
    )


def bundle_directory_complete(
    directory: Path,
    fingerprint: str,
    *,
    pipeline_id: str | None = None,
) -> bool:
    """Check that a cached/runtime directory contains every manifest-owned artifact."""
    if not directory.is_dir() or directory.is_symlink() or not _fingerprint(fingerprint):
        return False
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(manifest, dict) or manifest.get("fingerprint") != fingerprint:
        return False
    pipeline = manifest.get("pipeline")
    if not isinstance(pipeline, dict):
        return False
    manifest_pipeline_id = pipeline.get("id")
    lineage = pipeline.get("lineage")
    if (
        not isinstance(manifest_pipeline_id, str)
        or not isinstance(lineage, list)
        or not lineage
        or any(not isinstance(item, str) for item in lineage)
        or lineage[-1] != manifest_pipeline_id
        or (pipeline_id is not None and manifest_pipeline_id != pipeline_id)
    ):
        return False
    required = set(_TOP_LEVEL_ARTIFACTS)
    plugins = manifest.get("plugins")
    if not isinstance(plugins, list):
        return False
    for provider in plugins:
        if not isinstance(provider, dict):
            return False
        plugin_id = provider.get("plugin_id")
        if not isinstance(plugin_id, str):
            return False
        agent_schema = provider.get("agent_schema")
        if not _add_manifest_path(required, agent_schema, key="path"):
            return False
        references = provider.get("references")
        if not isinstance(references, list):
            return False
        for reference in references:
            if not isinstance(reference, dict):
                return False
            path = reference.get("path")
            if not isinstance(path, str):
                return False
            if not _add_path(required, f"plugins/{plugin_id}/{path}"):
                return False
    node_kinds = manifest.get("node_kinds")
    if node_kinds is not None:
        if not isinstance(node_kinds, dict):
            return False
        if not _add_manifest_path(required, node_kinds.get("agent_schema"), key="path"):
            return False
        references = node_kinds.get("references")
        if not isinstance(references, list):
            return False
        for reference in references:
            if not _add_manifest_path(required, reference, key="path"):
                return False
    return all(_regular_file(directory / path) for path in required)


def load_cached_bundle(
    root: Path,
    fingerprint: str,
    *,
    pipeline_id: str = ECLAB_SCHEMA_PIPELINE_ID,
) -> CompiledSchemaBundle:
    """Load a complete cached bundle for a consumer whose target needs refreshing."""
    directory = _pipeline_root(root, pipeline_id) / "artifacts" / fingerprint
    if not bundle_directory_complete(directory, fingerprint, pipeline_id=pipeline_id):
        raise RuntimeError(f"cached runtime schema bundle is incomplete: {fingerprint}")
    manifest_bytes = (directory / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    pipeline = manifest["pipeline"]
    plugin_schemas: list[CompiledPluginSchema] = []
    references: list[CompiledReference] = []
    for plugin_id, path in _agent_schema_paths(manifest):
        content = (directory / "plugins" / plugin_id / path).read_bytes()
        plugin_schemas.append(
            CompiledPluginSchema(
                plugin_id,
                path,
                content,
                hashlib.sha256(content).hexdigest(),
            )
        )
    for plugin_id, path, title in _reference_paths(manifest):
        content = (directory / "plugins" / plugin_id / path).read_bytes()
        references.append(
            CompiledReference(
                plugin_id,
                path,
                title,
                content,
                hashlib.sha256(content).hexdigest(),
            )
        )
    return CompiledSchemaBundle(
        fingerprint=fingerprint,
        manifest=manifest_bytes,
        topology_schema=(directory / "clab.schema.json").read_bytes(),
        catalog_json=(directory / "catalog.json").read_bytes(),
        catalog_markdown=(directory / "catalog.md").read_bytes(),
        references=tuple(references),
        plugin_schemas=tuple(plugin_schemas),
        pipeline_id=pipeline_id,
        pipeline_lineage=tuple(pipeline["lineage"]),
    )


def cache_record(
    input_fingerprint: str,
    bundle_fingerprint: str,
    *,
    pipeline_id: str = ECLAB_SCHEMA_PIPELINE_ID,
    pipeline_lineage: tuple[str, ...] | None = None,
) -> bytes:
    SchemaPipeline(pipeline_id)
    lineage = (pipeline_id,) if pipeline_lineage is None else pipeline_lineage
    return (
        json.dumps(
            {
                "cache_format": CACHE_FORMAT_VERSION,
                "fingerprint": bundle_fingerprint,
                "input_fingerprint": input_fingerprint,
                "pipeline_id": pipeline_id,
                "pipeline_lineage": list(lineage),
            },
            sort_keys=True,
        )
        + "\n"
    ).encode()


def _pipeline_root(root: Path, pipeline_id: str) -> Path:
    SchemaPipeline(pipeline_id)
    return root / "pipelines" / pipeline_id


def _agent_schema_paths(manifest: dict[str, object]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    plugins = manifest.get("plugins")
    if isinstance(plugins, list):
        for provider in plugins:
            if not isinstance(provider, dict):
                continue
            agent_schema = provider.get("agent_schema")
            if isinstance(agent_schema, dict):
                result.append(_split_plugin_path(agent_schema.get("path")))
    node_kinds = manifest.get("node_kinds")
    if isinstance(node_kinds, dict):
        agent_schema = node_kinds.get("agent_schema")
        if isinstance(agent_schema, dict):
            result.append(_split_plugin_path(agent_schema.get("path")))
    return result


def _reference_paths(manifest: dict[str, object]) -> list[tuple[str, str, str | None]]:
    result: list[tuple[str, str, str | None]] = []
    plugins = manifest.get("plugins")
    if isinstance(plugins, list):
        for provider in plugins:
            if not isinstance(provider, dict) or not isinstance(provider.get("plugin_id"), str):
                continue
            plugin_id = provider["plugin_id"]
            references = provider.get("references")
            if not isinstance(references, list):
                continue
            for reference in references:
                if not isinstance(reference, dict):
                    continue
                title = reference.get("title")
                result.append(
                    (
                        plugin_id,
                        _safe_relative_path(reference.get("path")),
                        title if isinstance(title, str) else None,
                    )
                )
    node_kinds = manifest.get("node_kinds")
    if isinstance(node_kinds, dict) and isinstance(node_kinds.get("references"), list):
        for reference in node_kinds["references"]:
            if not isinstance(reference, dict):
                continue
            plugin_id, path = _split_plugin_path(reference.get("path"))
            title = reference.get("title")
            result.append((plugin_id, path, title if isinstance(title, str) else None))
    return result


def _split_plugin_path(value: object) -> tuple[str, str]:
    path = PurePosixPath(_safe_relative_path(value))
    if len(path.parts) < 3 or path.parts[0] != "plugins":
        raise RuntimeError("cached manifest contains an invalid plugin artifact path")
    return path.parts[1], PurePosixPath(*path.parts[2:]).as_posix()


def _safe_relative_path(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("cached manifest contains an invalid artifact path")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise RuntimeError("cached manifest contains an unsafe artifact path")
    return path.as_posix()


def _containerlab_input(
    hint: ContainerlabSourceHint,
    environment: Mapping[str, str],
) -> dict[str, object]:
    value: dict[str, object] = {
        "kind": hint.kind.value,
        "repository": hint.repository,
        "revision": hint.revision,
    }
    if hint.kind is ContainerlabSourceKind.CHECKOUT and hint.checkout is not None:
        value["checkout"] = _containerlab_checkout(hint.checkout)
    elif hint.kind is ContainerlabSourceKind.BINARY and hint.binary is not None:
        binary = hint.binary.expanduser().resolve()
        value["binary"] = _file_stamp(binary)
        checkout = checkout_for_binary(binary)
        if checkout is not None:
            value["checkout"] = _containerlab_checkout(checkout)
        override = environment.get("CONTAINERLAB_SCHEMA", "").strip()
        if override:
            value["schema_override"] = _file_stamp(
                Path(override).expanduser().resolve(),
                digest=True,
            )
    return value


def _vrnetlab_input(
    hint: VrnetlabSourceHint | None,
    environment: Mapping[str, str],
) -> dict[str, object]:
    if hint is not None and hint.checkout is not None and _valid_vrnetlab(hint.checkout):
        return {"checkout": _vrnetlab_checkout(hint.checkout)}
    configured = environment.get("VRNETLAB_DIR", "").strip()
    if configured:
        checkout = Path(configured).expanduser().resolve()
        if _valid_vrnetlab(checkout):
            return {"checkout": _vrnetlab_checkout(checkout)}
    return {
        "repository": (
            hint.repository
            if hint is not None and hint.repository is not None
            else environment.get("VRNETLAB_REPO", "").strip() or None
        ),
        "revision": (
            hint.revision
            if hint is not None and hint.revision is not None
            else environment.get("VRNETLAB_VERSION", "").strip() or None
        ),
    }


def _containerlab_checkout(checkout: Path) -> dict[str, object]:
    root = checkout.expanduser().resolve()
    return {
        "path": str(root),
        "revision": _git(root, "rev-parse", "HEAD"),
        "repository": _git(root, "remote", "get-url", "origin"),
        "schema": _file_stamp(root / SCHEMA_RELATIVE, digest=True),
        "kind_docs": _tree_stamp(root / "docs" / "manual" / "kinds"),
    }


def _vrnetlab_checkout(checkout: Path) -> dict[str, object]:
    root = checkout.expanduser().resolve()
    return {
        "path": str(root),
        "revision": _git(root, "rev-parse", "HEAD"),
        "repository": _git(root, "remote", "get-url", "origin"),
        "readmes": _tree_stamp(root, readmes_only=True, max_depth=3),
    }


def _valid_vrnetlab(checkout: Path) -> bool:
    return checkout.is_dir() and (checkout / "common" / "vrnetlab.py").is_file()


def _tree_stamp(
    root: Path,
    *,
    readmes_only: bool = False,
    max_depth: int | None = None,
) -> list[list[object]]:
    if not root.is_dir() or root.is_symlink():
        return []
    result: list[list[object]] = []
    for current, directories, files in os.walk(root, followlinks=False):
        directory = Path(current)
        depth = len(directory.relative_to(root).parts)
        directories[:] = [
            name
            for name in directories
            if name != ".git"
            and not (directory / name).is_symlink()
            and (max_depth is None or depth < max_depth - 1)
        ]
        for name in files:
            if readmes_only and name.casefold() not in _README_NAMES:
                continue
            path = directory / name
            if path.is_symlink():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            result.append([path.relative_to(root).as_posix(), stat.st_size, stat.st_mtime_ns])
    result.sort(key=lambda item: str(item[0]))
    return result


def _file_stamp(path: Path, *, digest: bool = False) -> dict[str, object]:
    value: dict[str, object] = {"path": str(path)}
    try:
        stat = path.stat()
    except OSError:
        value["missing"] = True
        return value
    value.update({"size": stat.st_size, "mtime_ns": stat.st_mtime_ns})
    if digest and path.is_file() and not path.is_symlink():
        try:
            value["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            value["unreadable"] = True
    return value


def _git(checkout: Path, *arguments: str) -> str | None:
    try:
        process = subprocess.run(
            ["git", "-C", str(checkout), *arguments],
            check=True,
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return process.stdout.decode("utf-8", errors="replace").strip() or None


def _stable(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _stable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bytes):
        return {"bytes_sha256": hashlib.sha256(value).hexdigest(), "size": len(value)}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple | list):
        return [_stable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _stable(item) for key, item in sorted(value.items())}
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise TypeError(f"unsupported schema cache input: {type(value).__name__}")


def _fingerprint(value: object) -> TypeGuard[str]:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _add_manifest_path(paths: set[str], value: object, *, key: str) -> bool:
    return isinstance(value, dict) and _add_path(paths, value.get(key))


def _add_path(paths: set[str], value: object) -> bool:
    if not isinstance(value, str):
        return False
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        return False
    paths.add(path.as_posix())
    return True


def _regular_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()
